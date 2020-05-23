from debian import deb822, debian_support
from pathlib import Path
import asyncio, gzip, logging, os, yaml, re
import micro_buildd_conf as conf

class Repo(object):
    async def scanArch(self, arch, res):
        proc = await asyncio.create_subprocess_exec('dose-builddebcheck',
                                                    f'--deb-native-arch={conf.rebuild_arch}',
                                                    '--deb-drop-b-d-arch' if arch == 'all' else '--deb-drop-b-d-indep',
                                                    '--deb-emulate-sbuild',
                                                    '--explain', '--successes', '--failures',
                                                    str(conf.rebuild_repo_packages_path),
                                                    str(conf.rebuild_repo_partial_packages_path),
                                                    str(conf.apt_sources_path),
                                                    stdin=asyncio.subprocess.DEVNULL,
                                                    stdout=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        # note, because dose-builddebcheck does not properly quote its
        # string values (such as "0xffff" package name), we intentionally use
        # yaml.CBaseLoader instead of yaml.CSafeLoader
        # see also: https://bugs.debian.org/cgi-bin/reportbug.cgi?bug=834059
        debbuildcheck_out = await asyncio.get_running_loop().run_in_executor(
            None, yaml.load, stdout, yaml.CBaseLoader)

        if arch == 'all':
            archFilter = ['all']
        elif arch == 'amd64':
            archFilter = ['amd64', 'any', 'linux-any', 'any-amd64']
        elif arch == 'i386':
            archFilter = ['i386', 'any', 'linux-any', 'any-i386']
        else:
            raise RuntimeError(f'unsupported arch {arch}')

        for entry in debbuildcheck_out['report']:
            if any(a in archFilter for a in entry['architecture'].split(',')):
                pkg = entry["package"]

                if entry['status'] == 'ok':
                    res[(pkg, arch)] = { 'Installed': False, 'Version': entry['version'], 'Buildable': True }
                elif entry['status'] == 'broken':
                    res[(pkg, arch)] = { 'Installed': False, 'Version': entry['version'], 'Buildable': False, 'Reasons': yaml.safe_dump(entry['reasons']) }

    async def scan(self):
        logging.info('Generating and processing package buildability info')

        res = {}

        await self.scanArch(conf.rebuild_arch, res)
        await self.scanArch('all', res)

        with open(conf.rebuild_repo_packages_path) as fh:
            for pkgentry in deb822.Packages.iter_paragraphs(fh, use_apt_pkg=False):
                arch = pkgentry['Architecture']
                vers = pkgentry['Version']
                try:
                    src = pkgentry['Source']
                    # e.g. Source: gcc-defaults (1.185.1)
                    if m := re.match('([^ ]*) [(](.*)[)]', src):
                        src = m[1]
                        vers = m[2]
                except KeyError:
                    src = pkgentry['Package']

                try:
                    resentry = res[(src, arch)]
                    if resentry['Version'] == vers:
                        resentry['Installed'] = True
                except KeyError:
                    pass

        return res

    async def process_incoming(self):
        logging.info('Processing incoming directory')
        proc = await asyncio.create_subprocess_exec('reprepro', 'processincoming', 'unstable',
                                                    cwd=conf.rebuild_repo_base_dir,
                                                    stdin=asyncio.subprocess.DEVNULL)
        await proc.wait()
        if proc.returncode != 0:
            logging.warn('reprepro processincoming failed')
