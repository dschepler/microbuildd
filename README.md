# microbuildd
This is a tiny Debian build daemon.  It does not support remote builders,
rather it performs all builds on the same machine.  It does support waiting
for build dependencies to become available, and it has no problems accepting
source-only uploads.

## Requirements
* Python 3
* reprepro
* dose-builddebcheck
* aiosqlite Python module
* python-debian Python module

## Setup
Configuration is currently handled by editing micro_buildd_conf.py.
