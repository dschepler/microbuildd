from pathlib import Path

"""
sbuild_key_id: the id the the GPG key to use in signing builds
"""
sbuild_key_id = '633ADD6478E206D95E40ECAA0BDA22B2788F37F7'

"""
maintainer: the maintainer string to use for builds
"""
maintainer = 'Daniel Schepler <dschepler@gmail.com>'

"""
rebuild_base_dir: base directory of the rebuild repositories,
logs, temporary build directories, etc.
"""
rebuild_base_dir = Path.home() / 'rebuild'

"""
rebuild_arch: architecture to rebuild for.
"""
rebuild_arch = 'amd64'

"""
sbuild_chroot_mode: the chroot backend to pass to sbuild commands
"""
sbuild_chroot_mode = 'systemd-nspawn'

"""
sbuild_chroot_name: the name of the chroot to use for sbuild commands
"""
sbuild_chroot_name = f'rebuild-{rebuild_arch}-sbuild'

"""
incoming_interval: interval in seconds at which to process the
incoming queue and reevaluate what packages can be built.  Note
this takes a significant amount of CPU time, so you might want
to avoid doing this too frequently.
"""
incoming_interval = 30 * 60

"""
chroot_update_interval: interval in seconds at which to update
the chroot.  (Note that each sbuild run also updates its snapshot
of the chroot, so this is mostly a matter of avoiding having to do
days and days worth of updates on each build after a while.)
"""
chroot_update_interval = 6 * 60 * 60

"""
apt_sources_path: path to the system apt main_sources_Sources file
"""
apt_sources_path = Path('/var/lib/apt/lists/localhost:3142_debian_dists_sid_main_source_Sources')

# settings below here should not normally need to be adjusted

"""
rebuild_logs_dir: directory in which logs are stored
"""
rebuild_logs_dir = rebuild_base_dir / 'logs'

"""
rebuild_chroot_update_log_path: filename of the chroot update log
"""
rebuild_chroot_update_log_path = rebuild_logs_dir / 'sbuild-update.log'

"""
rebuild_tmp_build_dir: directory to use for temporary working space
for the builds
"""
rebuild_tmp_build_dir = rebuild_base_dir / 'build'

"""
rebuild_repo_base_dir: base directory of the main rebuild repository
"""
rebuild_repo_base_dir = rebuild_base_dir / 'repo'

"""
rebuild_repo_incoming_dir: incoming directory of the main rebuild repository
"""
rebuild_repo_incoming_dir = rebuild_repo_base_dir / 'incoming'

"""
rebuild_repo_packages_path: path to the main rebuild repository's Packages file
"""
rebuild_repo_packages_path = rebuild_repo_base_dir / f'dists/sid/main/binary-{rebuild_arch}/Packages'

"""
rebuild_repo_udeb_packages_path: path to the main rebuild repository's udeb Packages file
"""
rebuild_repo_udeb_packages_path = rebuild_repo_base_dir / f'dists/sid/main/debian-installer/binary-{rebuild_arch}/Packages'

"""
rebuild_repo_partial_base_dir: base directory of the partial rebuild repository
"""
rebuild_repo_partial_base_dir = rebuild_base_dir / 'repo-partial'

"""
rebuild_repo_partial_packages_path: path to the partial rebuild repository's Packages file
"""
rebuild_repo_partial_packages_path = rebuild_repo_partial_base_dir / f'dists/partial/main/binary-{rebuild_arch}/Packages'

"""
database_path: the path to the sqlite database file
"""
database_path = rebuild_base_dir / 'microbuildd.sqlite'
