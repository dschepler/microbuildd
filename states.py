import aiosqlite, asyncio, logging
from pathlib import Path
import micro_buildd_conf as conf

class States(object):

    db = None
    db_updated_cond = None

    def __init__(self, lock):
        self.db_updated_cond = asyncio.Condition(lock)

    async def init(self):
        self.db = await aiosqlite.connect(conf.database_path)
        self.db.row_factory = aiosqlite.Row

        await self.ensure_db()

    async def shutdown(self):
        await self.db.close()
        self.db = None

    def state_for_avail(self, avail):
        if avail['Installed']:
            return 'Installed'
        elif avail['Buildable']:
            return 'Needs-Build'
        else:
            return 'BD-Uninstallable'

    def reasons_for_avail(self, avail):
        if avail['Installed'] or avail['Buildable']:
            return ''
        else:
            return avail['Reasons']

    async def ensure_db(self):
        await self.db.execute("""CREATE TABLE IF NOT EXISTS "states"
            ("RowId" INTEGER PRIMARY KEY,
             "Package" TEXT,
             "Architecture" TEXT,
             "Version" TEXT,
             "State" TEXT,
             "BDUninstallableReasons" TEXT,
             "Timestamp" TEXT,
             "BinNMUVersion" INTEGER,
             "BinNMUChangelog" TEXT,
             UNIQUE("Package", "Architecture"))
        """)
        
    async def update(self, repo):
        """
        Based on the differences between what repo.scan() finds and the current state,
        the following state transitions are possible:

        - New package: create new row with current Timestamp
        - Obsolete package: delete row
        - New version: update full row (including new state of Needs-Build or
            BD-Uninstallable), update Timestamp
        - Any -> Installed: remove any BD-Uninstallable-Reasons, update Timestamp
        - BD-Uninstallable -> Needs-Build: remove BD-Uninstallable-Reasons, update Timestamp
        - Needs-Build -> BD-Uninstallable: add BD-Uninstallable-Reasons, update Timestamp
        - BD-Uninstallable -> BD-Uninstallable with changed BD-Uninstallable-Reasons:
            update BD-Uninstallable-Reasons, do not update Timestamp

        Note that transitions into Building, Attempted, Uploaded, Failed, Given-Back are
        handled elsewhere - other than the obsolete package and new version cases, or
        transitioning into Installed, rows in these states should not be updated
        """

        availpkgs = await repo.scan()

        logging.info('Updating sqlite database from repository status')

        await self.ensure_db()

        newpkgs = []
        obsoletes = []
        newvers = []
        newinst = []
        bduninst_to_needsbuild = []
        needsbuild_to_bduninst = []
        bduninst_changed_reasons = []
        async with self.db.execute("SELECT * FROM states") as cursor:
            async for row in cursor:
                if (row['Package'], row['Architecture']) in availpkgs:
                    availentry = availpkgs[(row['Package'], row['Architecture'])]
                    availentry['InDB'] = True
                    if availentry['Version'] != row['Version']:
                        newvers += [{'RowId': row['RowId'], 'Version': availentry['Version'],
                                     'State': self.state_for_avail(availentry),
                                     'Reasons': self.reasons_for_avail(availentry)}]
                    elif availentry['Installed'] and row['State'] != 'Installed' and availentry['BinNMUVersion'] == row['BinNMUVersion']:
                        newinst += [{'RowId': row['RowId']}]
                    elif availentry['Buildable'] and row['State'] == 'BD-Uninstallable':
                        bduninst_to_needsbuild += [{'RowId': row['RowId']}]
                    elif not availentry['Buildable'] and row['State'] == 'Needs-Build':
                        needsbuild_to_bduninst += [{'RowId': row['RowId'], 'Reasons': availentry['Reasons']}]
                    elif (not availentry['Buildable'] and row['State'] == 'BD-Uninstallable' and
                          availentry['Reasons'] != row['BDUninstallableReasons']):
                        bduninst_changed_reasons += [{'RowId': row['RowId'], 'Reasons': availentry['Reasons']}]
                else:
                    obsoletes += [{'RowId': row['RowId']}]

            for ((pkg, arch), availentry) in availpkgs.items():
                if 'InDB' not in availentry:
                    newpkgs += [{'Package': pkg, 'Architecture': arch, 'Version': availentry['Version'],
                                 'State': self.state_for_avail(availentry),
                                 'Reasons': self.reasons_for_avail(availentry)}]

        await self.db.executemany("""INSERT INTO states (Package, Architecture, Version, State, BDUninstallableReasons, Timestamp)
            VALUES (:Package, :Architecture, :Version, :State, :Reasons, datetime('now'))
            """, newpkgs)
        await self.db.executemany("""DELETE FROM states WHERE RowId == :RowId""", obsoletes)
        await self.db.executemany("""UPDATE states
            SET Version = :Version,
                State = :State,
                BDUninstallableReasons = :Reasons,
                Timestamp = datetime('now'),
                BinNMUVersion = null,
                BinNMUChangelog = ''
            WHERE RowId == :RowId
            """, newvers)
        await self.db.executemany("""UPDATE states
            SET State = 'Installed',
                BDUninstallableReasons = '',
                Timestamp = datetime('now')
            WHERE RowId == :RowId
            """, newinst)
        await self.db.executemany("""UPDATE states
            SET State = 'Needs-Build',
                BDUninstallableReasons = '',
                Timestamp = datetime('now')
            WHERE RowId == :RowId
            """, bduninst_to_needsbuild)
        await self.db.executemany("""UPDATE states
            SET State = 'BD-Uninstallable',
                BDUninstallableReasons = :Reasons,
                Timestamp = datetime('now')
            WHERE RowId == :RowId
            """, needsbuild_to_bduninst)
        await self.db.executemany("""UPDATE states
            SET BDUninstallableReasons = :Reasons
            WHERE RowId == :RowId
            """, bduninst_changed_reasons)

        await self.db.commit()

        self.db_updated_cond.notify_all()

    async def register_log(self, loginfo):
        await self.db.execute("""CREATE TABLE IF NOT EXISTS "logs"
            ("RowId" INTEGER PRIMARY KEY,
             "Filename" TEXT UNIQUE,
             "Package" TEXT,
             "Version" TEXT,
             "Status" TEXT,
             "PackageTime" INTEGER,
             "Space" INTEGER,
             "StartTimestamp" TEXT,
             "EndTimestamp" TEXT)
            """)
        await self.db.execute("""
            INSERT INTO logs (Filename, Package, Version, Status, PackageTime, Space, StartTimestamp, EndTimestamp)
                VALUES (:Filename, :Package, :Version, :Status, :PackageTime, :Space, datetime(:StartTimestamp), datetime(:EndTimestamp))
            """, loginfo)
        await self.db.commit()

    class BuildLease(object):
        statesdb = None
        package = None
        architecture = None
        version = None
        binnmu_version = None
        binnmu_changelog = None
        build_result = None
        
        def __init__(self, statesdb):
            self.statesdb = statesdb
            self.package = None
            self.version = None
            self.build_result = None

        async def __aenter__(self):
            (self.package, self.architecture, self.version, self.binnmu_version, self.binnmu_changelog) = await self.statesdb._get_package_to_build()
            return self

        async def set_build_result(self, newstate):
            self.build_result = newstate
            await self.statesdb.register_build_result(self.package, self.architecture, self.version, self.binnmu_version, newstate)

        async def __aexit__(self, *exc):
            if self.package is not None and self.build_result is None:
                logging.info(f'Build lease for {self.package} version {self.versionstr()} terminated unexpectedly, setting State to Internal-Error')
                await self.set_build_result('Internal-Error')

        def versionstr(self):
            return self.version if self.binnmu_version is None else f'{self.version}+b{self.binnmu_version}'

    def get_package_to_build(self):
        return States.BuildLease(self)

    async def _get_package_to_build(self):
        while True:
            async with self.db.execute("""SELECT * FROM states WHERE State == "Needs-Build"
                ORDER BY Timestamp ASC
                LIMIT 1""") as cursor:
                async for row in cursor:
                    await self.db.execute("""UPDATE states
                        SET State = "Building",
                            Timestamp = datetime('now')
                        WHERE RowId == :RowId""",
                        {'RowId': row['RowId']})
                    await self.db.commit()
                    return (row['Package'], row['Architecture'], row['Version'], row['BinNMUVersion'], row['BinNMUChangelog'])

            await self.db_updated_cond.wait()

    async def register_build_result(self, package, architecture, version, binnmu_version, newstate):
        if binnmu_version is None:
            await self.db.execute("""UPDATE states
                SET State = :Newstate,
                    Timestamp = datetime('now')
                WHERE Package == :Package AND Architecture == :Architecture AND Version == :Version AND BINNMUVersion IS NULL AND State == "Building"
                """, {'Package': package, 'Architecture': architecture, 'Version': version, 'BinNMUVersion': binnmu_version, 'Newstate': newstate})
        else:
            await self.db.execute("""UPDATE states
                SET State = :Newstate,
                    Timestamp = datetime('now')
                WHERE Package == :Package AND Architecture == :Architecture AND Version == :Version AND BinNMUVersion == :BinNMUVersion AND State == "Building"
                """, {'Package': package, 'Architecture': architecture, 'Version': version, 'BinNMUVersion': binnmu_version, 'Newstate': newstate})
        await self.db.commit()
