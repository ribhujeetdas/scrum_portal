# SQLite Operations

## Supported topology

Use one local, file-backed SQLite database and one application process. Waitress threads may serve multiple local users concurrently; writes are short, serialized transactions. Never place the active database on a network share or run a second application process against it.

## Journal and durability

`SQLITE_JOURNAL_MODE=DELETE` and `SQLITE_SYNCHRONOUS=FULL` are the safe defaults across the supported Windows/Linux environments. `scripts/database_configure.py` refuses unsupported journal settings and refuses WAL when the running SQLite version is in the known unsafe range. Run it only while the server is stopped.

## Backup

`python scripts/backup_db.py` uses SQLite's online backup API, runs integrity and foreign-key checks on the copy, writes a SHA-256 metadata sidecar, and prunes only backups beyond configured retention. A backup is not complete without its matching `.json` file.

Backups should be tested periodically by restoring to a disposable installation and running `check_db.py`, migration status, and smoke tests. Retention count is not a substitute for copying backups away from the active disk under the organization's approved storage procedure.

## Restore

Stop the server, then run `python scripts/restore_db.py --backup <path> --confirm`. The command requires matching metadata, verifies the checksum and source database, locks the target, takes a safety backup, uses atomic replacement, and validates the restored file. If post-restore validation fails, leave the server stopped and use the reported safety backup.

## Schema migration

Run `python scripts/migrate_db.py` while the server is stopped. A fresh database is created at the current schema and stamped at Alembic head. An existing database is backed up and upgraded. Partial schemas, unparseable legacy Sprint timestamps, or a non-current final head fail the command instead of guessing.

Do not edit SQLite tables manually to simulate migrations. Do not use `flask init-db` or `db.create_all()` for an existing installation.

## Integrity and capacity

- `python scripts/check_db.py`: integrity, foreign keys, journal, SQLite version.
- `python scripts/diagnose.py`: sanitized app/database/migration/log/disk report.
- `/health/ready`: continuous lightweight readiness signal.

Treat `database is locked`, foreign-key violations, integrity failures, low disk, a stale migration head, or a second-process lock error as operational incidents. Preserve the request ID, diagnostic output, relevant log interval, application version, and backup metadata; never include secrets.
