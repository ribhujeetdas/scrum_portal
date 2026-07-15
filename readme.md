# Scrum Portal

Cross-platform Flask portal for Jira automation, Sprint reporting, Tableau
custom-view mapping, and TCI workflows. The supported production topology is
one Waitress process with multiple worker threads and one local SQLite database.

## Prerequisites

- Python 3.12 (64-bit recommended).
- Access to an approved Python package index for the first dependency install.
- Reachable Jira Data Center and Tableau Server base URLs.
- A Jira account and personal access token (PAT) for the first signup.
- A short, local installation path such as `C:\scrum_portal` or
  `/opt/scrum_portal`. Do not run the database from a network or synchronized
  folder.

Do not copy an existing `.venv` between computers or operating systems. Create
a new virtual environment on the target Windows or Linux host.

## 1. Install dependencies

The hash-locked development requirements include the runtime packages and the
local verification tools.

### Windows PowerShell

```powershell
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.txt
Copy-Item .env.example .env
```

### Linux

```bash
python3.12 --version
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
cp .env.example .env
```

For a runtime-only installation, use `requirements.txt` instead. Run the full
verification gate on a machine that has `requirements-dev.txt` installed.

## 2. Configure `.env`

Generate two independent keys. Run the commands for your platform and copy the
outputs into the corresponding `.env` values.

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Linux

```bash
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Before continuing, edit `.env` and replace at least these example values:

| Setting | Required value |
| --- | --- |
| `SECRET_KEY` | First generated random value; never reuse the Fernet key. |
| `FERNET_KEY` | Second generated Fernet value; keep it stable or stored PATs cannot be decrypted. |
| `ADMIN_EMAIL` | Address users should contact for account support. |
| `JIRA_BASE_URL` | Jira origin, for example `https://jira.company.example`. |
| `TABLEAU_BASE_URL` | Tableau origin, for example `https://tableau.company.example`. |
| `JIRA_AUTOMATION_ACTOR_ACCOUNT_ID` | Jira automation actor account ID used by rule-copy workflows. |
| `APPLICATION_VERSION` | Local release identifier shown in health checks and logs. |

Keep `APP_ENV=production`, `SQLITE_JOURNAL_MODE=DELETE`,
`SQLITE_SYNCHRONOUS=FULL`, and `DATABASE_INSTANCE_LOCK=true` for the supported
deployment. `SESSION_COOKIE_SECURE=false` is required for plain local HTTP; set
it to `true` only when the application is actually served over HTTPS.

Never commit `.env`, PATs, generated keys, database files, backups, or logs.

## 3. Initialize and verify

Run every command from the repository root. Stop if any command returns a
non-zero exit code.

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe scripts\migrate_db.py
.\.venv\Scripts\python.exe scripts\database_configure.py
.\.venv\Scripts\python.exe scripts\verify.py
.\.venv\Scripts\python.exe scripts\diagnose.py
```

### Linux

```bash
.venv/bin/python scripts/migrate_db.py
.venv/bin/python scripts/database_configure.py
.venv/bin/python scripts/verify.py
.venv/bin/python scripts/diagnose.py
```

The final diagnostic JSON must contain `"ok": true`, foreign keys enabled, and
the current migration head. The verification gate runs compilation, linting,
formatting, type checks, security and dependency audits, tests with coverage,
and a route smoke check.

## 4. Run the application

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe scripts\run_server.py
```

### Linux

```bash
.venv/bin/python scripts/run_server.py
```

On the application host, open:

- Readiness: `http://127.0.0.1:5000/health/ready`
- First account: `http://127.0.0.1:5000/auth/signup`
- Login: `http://127.0.0.1:5000/auth/login`

The readiness response must return HTTP 200 with `"ok": true`. For the first
account, enter the Jira email and PAT, confirm the Jira profile, then set the
portal password. The Jira identity must be active and its email must match the
submitted email.

Stop the server with `Ctrl+C`. Application and audit events are written to
`logs/app.log` and `logs/audit.log` unless `.env` changes those paths.

## Existing installation or manual release copy

Do not copy `.git`, `.venv`, `.worktrees`, caches, logs, backups, or local
database files. Build a source-only archive and extract it into a short path:

```text
git archive --format=zip --output scrum-portal-release.zip HEAD
```

Preserve the target `.env`, `instance/`, `logs/`, and `backups/`. Before
replacing code or migrating an existing database, follow the manual deployment
and SQLite backup/restore runbooks below.

## Documentation

- [First-time setup](docs/first_time_setup.md)
- [Manual deployment](docs/manual_deployment.md)
- [Environment reference](docs/env_reference.md)
- [SQLite operations](docs/sqlite_operations.md)
- [Operations and tracing](docs/operations.md)
- [Architecture](docs/architecture.md)
- [Route map](docs/routes.md)
- [Code review graph](docs/code_review_graph.md)

## Repository rules

- Never run more than one application process against the database.
- Change schema only through an Alembic migration and take a verified backup
  first.
- Keep compatibility routes thin; new behavior belongs in `app/features` or
  shared `app/core` services.
- Run `scripts/verify.py` before every manual deployment.
