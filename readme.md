# Scrum Portal

Cross-platform Flask portal for Jira automation, Sprint reporting, Tableau custom-view mapping, and TCI workflows. The supported production topology is one Waitress process with multiple worker threads and one local SQLite database.

## Quick Start

Use Python 3.12. The locked files include hashes so Windows and Linux install the same reviewed dependency versions.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.txt
Copy-Item .env.example .env
# Replace every secret and service placeholder in .env
.\.venv\Scripts\python.exe scripts\migrate_db.py
.\.venv\Scripts\python.exe scripts\database_configure.py
.\.venv\Scripts\python.exe scripts\verify.py
.\.venv\Scripts\python.exe scripts\run_server.py
```

Linux uses the equivalent `.venv/bin/python` commands. See the setup guide before using production mode.

## Documentation

- [First-time setup](docs/first_time_setup.md)
- [Manual deployment](docs/manual_deployment.md)
- [Environment reference](docs/env_reference.md)
- [SQLite operations](docs/sqlite_operations.md)
- [Operations and tracing](docs/operations.md)
- [Architecture](docs/architecture.md)
- [Route map](docs/routes.md)
- [Code review graph](docs/code_review_graph.md)

## Repository Rules

- Never run more than one application process against the database.
- Never commit `.env`, database files, backups, logs, PATs, or verification artifacts.
- Change schema only through an Alembic migration and take a verified backup first.
- Keep compatibility routes thin; new behavior belongs in `app/features` or shared `app/core` services.
- Run `scripts/verify.py` before a manual deployment.
