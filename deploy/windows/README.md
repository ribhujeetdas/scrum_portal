# Windows service setup

Create two services with the organization's approved Windows service manager: one for the Waitress command and one for `python -m workers.sprint_import_worker`. Do not run either from an interactive user profile.

Configure both with:

- Working directory `D:\ScrumPortal\app` (or the approved deployment directory).
- Executables from the deployment virtual environment.
- The same service account, environment, Fernet key, and absolute local SQLite path.
- Hidden/noninteractive process windows, automatic restart with bounded delay, and a graceful stop timeout of at least 30 seconds.
- Modify permission for the database, WAL/SHM files, log directory, and backup target; read permission for application files and secrets.

Use the commands in `deploy/waitress.md`. Check the three health endpoints after every restart. The worker leader lease rejects an overlapping second worker; investigate instead of repeatedly launching another process.
