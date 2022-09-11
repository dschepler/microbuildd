from debian import deb822, debian_support
from pathlib import Path
import asyncio, gzip, logging, os, yaml, re
import micro_buildd_conf as conf

class Repo(object):
    def scanSrcs(self):
        res = {}
        with open(conf.apt_sources_path) as fh:
            for srcentry in deb822.Sources.iter_paragraphs(fh, use_apt_pkg=False):
                oldentry = res.get(srcentry["Package"], None)
                if oldentry is None or debian_support.Version(oldentry["Version"]) < debian_support.Version(srcentry["Version"]):
                    res[srcentry["Package"]] = srcentry

        # now exclude entries where the latest package is marked as
        # Extra-Source-Only: yes
        eso_srcs = set()
        for k, v in res.items():
            if v.get("Extra-Source-Only", "no") == "yes":
                eso_srcs.add(k)
        for k in eso_srcs:
            del res[k]

        return res

    async def scanArch(self, arch, srcs, res):
        if arch == 'all':
            archFilter = ['all']
        elif arch == 'amd64':
            archFilter = ['amd64', 'any', 'linux-any', 'any-amd64']
        elif arch == 'i386':
            archFilter = ['i386', 'any', 'linux-any', 'any-i386']
        else:
            raise RuntimeError(f'unsupported arch {arch}')

        debNativeArch = conf.rebuild_indep_build_arch if arch == 'all' else arch
        for pkg, entry in srcs.items():
            if any(a in archFilter for a in entry["Architecture"].split()):
                res[(pkg, arch)] = { 'Installed': False, 'Version': entry['Version'], 'Buildable': False, 'Reasons': 'unevaluated', 'BinNMUVersion': None }

        proc = await asyncio.create_subprocess_exec('dose-builddebcheck',
                                                    f'--deb-native-arch={debNativeArch}',
                                                    '--deb-drop-b-d-arch' if arch == 'all' else '--deb-drop-b-d-indep',
                                                    '--deb-emulate-sbuild',
                                                    '--successes',
                                                    str(conf.rebuild_repo_packages_path(debNativeArch)),
                                                    str(conf.rebuild_repo_partial_packages_path(debNativeArch)),
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

        for entry in debbuildcheck_out['report']:
            if any(a in archFilter for a in entry['architecture'].split(',')):
                pkg = entry['package']
                resentry = res.get((pkg, arch), None)
                if resentry is not None and resentry['Version'] == entry['version']:
                    resentry['Buildable'] = True
                    del resentry['Reasons']

        proc = await asyncio.create_subprocess_exec('dose-builddebcheck',
                                                    f'--deb-native-arch={debNativeArch}',
                                                    '--deb-drop-b-d-arch' if arch == 'all' else '--deb-drop-b-d-indep',
                                                    '--deb-emulate-sbuild',
                                                    '--explain', '--failures',
                                                    str(conf.rebuild_repo_packages_path(debNativeArch)),
                                                    str(conf.rebuild_repo_partial_packages_path(debNativeArch)),
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

        for entry in debbuildcheck_out['report']:
            if any(a in archFilter for a in entry['architecture'].split(',')):
                pkg = entry['package']
                resentry = res.get((pkg, arch), None)
                if resentry is not None and resentry['Version'] == entry['version']:
                    resentry['Buildable'] = False
                    resentry['Reasons'] = yaml.safe_dump(entry['reasons'])

    async def scan(self):
        logging.info('Generating and processing package buildability info')

        res = {}

        srcs = self.scanSrcs()

        for arch in conf.rebuild_archs:
            await self.scanArch(arch, srcs, res)
        await self.scanArch('all', srcs, res)

        for buildArch in conf.rebuild_archs:
            for packages_path in (conf.rebuild_repo_packages_path(buildArch), conf.rebuild_repo_udeb_packages_path(buildArch)):
                with open(packages_path) as fh:
                    for pkgentry in deb822.Packages.iter_paragraphs(fh, use_apt_pkg=False):
                        arch = pkgentry['Architecture']
                        vers = pkgentry['Version']
                        src = pkgentry.get('Source', pkgentry['Package'])
                        binnmuver = None

                        # remove +b<n> from tail and put <n> into BinNMUVersion
                        if m := re.match('(.*)\+b([0-9]+)', vers):
                            vers = m[1]
                            binnmuver = int(m[2])

                        # handle e.g. Source: gcc-defaults (1.185.1)
                        # note: in combination of binNMU with modified package
                        # version, the package gets e.g.
                        # Source: gcc-defaults (1.185.1)
                        # Version: 10.3.1+b1
                        if m := re.match('([^ ]*) [(](.*)[)]', src):
                            src = m[1]
                            vers = m[2]

                        resentry = res.get((src, arch), None)
                        if resentry is not None and resentry['Version'] == vers:
                            resentry['Installed'] = True
                            if binnmuver is not None and (resentry['BinNMUVersion'] is None or binnmuver > resentry['BinNMUVersion']):
                                resentry['BinNMUVersion'] = binnmuver

        return res

    async def process_incoming(self):
        logging.info('Processing incoming directory')
        proc = await asyncio.create_subprocess_exec('reprepro', 'processincoming', 'unstable',
                                                    cwd=conf.rebuild_repo_base_dir,
                                                    stdin=asyncio.subprocess.DEVNULL)
        await proc.wait()
        if proc.returncode != 0:
            logging.warn('reprepro processincoming failed')
