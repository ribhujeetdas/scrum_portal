# First-Time Setup

Python 3.12 is required. Keep the repository, virtual environment, SQLite file, logs, and backups on a local disk rather than a synchronized or network-mounted folder.

## Windows

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.txt
Copy-Item .env.example .env
```

## Linux

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
cp .env.example .env
```

Generate independent keys and place them only in `.env`:

```text
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set `SECRET_KEY` to the first value and `FERNET_KEY` to the second. Replace the Jira, Tableau, administrator, and runtime placeholders. Production startup fails closed if secrets are weak, URLs are malformed, SQLite is not file-backed, or a requested WAL mode is unsafe.

Initialize or upgrade the database, apply its configured journal mode, then run the local quality gate:

```text
python scripts/migrate_db.py
python scripts/database_configure.py
python scripts/verify.py
python scripts/diagnose.py
```

Start the production server with `python scripts/run_server.py`. `wsgi.py` only exports the WSGI application for tooling; it is not a development-server launcher.

For an existing installation, read [Manual deployment](manual_deployment.md) and [SQLite operations](sqlite_operations.md) before replacing code or changing schema.
