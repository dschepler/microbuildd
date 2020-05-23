from pathlib import Path
import asyncio, logging, os, re, shutil, warnings
from debian import deb822
from contextlib import contextmanager
import micro_buildd_conf as conf

class Chroot(object):
    async def update(self):
        logging.info('Updating build chroot')
        with open(conf.rebuild_chroot_update_log_path, 'w') as outfile:
            proc = await asyncio.create_subprocess_exec(
                'sbuild-update', f'--chroot-mode={conf.sbuild_chroot_mode}', '--update', '--dist-upgrade', '--autoremove', conf.sbuild_chroot_name,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=outfile,
                stderr=asyncio.subprocess.STDOUT)
            await proc.wait()
        if proc.returncode != 0:
            logging.warning(f'sbuild-update process failed, see {str(conf.rebuild_chroot_update_log_path)}')

    @contextmanager
    def mkbuilddir(self, package, architecture, version):
        path = conf.rebuild_tmp_build_dir / f'{package}:{architecture}_{version}'
        os.mkdir(path)
        try:
            yield path
        finally:
            shutil.rmtree(path)

    async def build(self, build_lease, statesdb):
        package = build_lease.package
        architecture = build_lease.architecture
        version = build_lease.version
        binnmu_version = build_lease.binnmu_version
        binnmu_changelog = build_lease.binnmu_changelog
        with self.mkbuilddir(package, architecture, version) as builddir:
            logging.info(f'Starting build of {package}:{architecture} version {build_lease.versionstr()}')
            proc = await asyncio.create_subprocess_exec(
                'sbuild', f'--chroot-mode={conf.sbuild_chroot_mode}', '-c', f'chroot:{conf.sbuild_chroot_name}', '-d', 'unstable',
                '--no-arch-any' if architecture == 'all' else '--no-arch-all',
                *((f'--binNMU={binnmu_version}', f'--make-binNMU={binnmu_changelog}') if binnmu_version is not None else ()),
                '-m', conf.maintainer,
                '--keyid', conf.sbuild_key_id, f'{package}_{version}',
                cwd=builddir,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL, # sbuild creates log file itself, no need to save redundant stdout
                stderr=asyncio.subprocess.DEVNULL)
            await proc.wait()

            # it's not technically necessary to hold the locks past this point - but
            # if we do, that means that if the incoming_loop was waiting for the lock
            # (which should happen on any build taking more than 5 minutes) then the
            # next iteration will pick up the new artifacts we will place there
            try:
                logfile = next(p for p in builddir.glob('*.build') if not p.is_symlink())
            except StopIteration:
                logging.warning('sbuild failed to create log file')
                return
            loginfo = self.scan_log(logfile)

            logging.info(f'Build of {package}:{architecture} version {build_lease.versionstr()} completed with status {loginfo["Status"]}')
            logfile.rename(conf.rebuild_logs_dir / logfile.name)
            await statesdb.register_log(loginfo)
            if loginfo['Status'] == 'successful':
                try:
                    changesfile = next(builddir.glob('*.changes'))
                except StopIteration:
                    logging.warning('sbuild failed to create changes file')
                    return
                incomingdir = conf.rebuild_repo_incoming_dir
                with open(changesfile) as fh:
                    changes = deb822.Changes(fh)
                    for fname in (entry['name'] for entry in changes['files']):
                        (builddir / fname).rename(incomingdir / fname)
                changesfile.rename(incomingdir / changesfile.name)
                await build_lease.set_build_result('Uploaded')
            elif loginfo['Status'] == 'attempted':
                await build_lease.set_build_result('Attempted')
            elif loginfo['Status'] == 'given-back':
                await build_lease.set_build_result('Given-Back')
            else:
                warnings.warn(f'Unrecognized status for build of {package} version {version}: {loginfo["Status"]}')
                await build_lease.set_build_result('Internal-Error')

    def scan_log(self, logpath):
        # use binary mode in case something in the build process
        # produced non UTF-8 output
        loglines = open(logpath, 'rb', buffering=False).readall().splitlines()
        
        # expected tail of sbuild log is:
        # <blank line>
        # Field: Value <repeated>
        # ------...
        # Finished at YYYY-MM-DDTHH:MM:SSZ
        # Build needed HH:MM:SS, NNNNk disk space
        # <possibly followed by some messages on GPG signing>
        res = {'Filename': logpath.name}

        try:
            idx = next(i for i in range(len(loglines)-1,-1,-1) if loglines[i].startswith(b'Finished at '))
        except StopIteration:
            raise RuntimeError('Invalid log file format')
        if idx < 2:
            raise RuntimeError('Invalid log file format')

        m = re.match('Finished at (.*)', loglines[idx].decode())
        if not m:
            raise RuntimeError('Invalid log file format')
        res['EndTimestamp'] = m[1]

        m = re.match('.*_.*_[^-]*-(.*)\.build', logpath.name)
        if not m:
            raise RuntimeError('Invalid log filename format')
        res['StartTimestamp'] = m[1]

        rawres = {}
        for l in (l.decode() for l in loglines[idx-2::-1]):
            if len(l) == 0:
                break
            parts = l.split(': ')
            if len(parts) != 2:
                raise RuntimeError('Invalid log file format')
            res[parts[0].translate({ord(' '): None, ord('-'): None})] = parts[1]

        return res
