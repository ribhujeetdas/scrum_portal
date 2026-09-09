# Scrum Portal

Flask application for Jira automation support, sprint reporting, Tableau custom view mapping, and TCI report workflows.

## Quick Start

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_windows.ps1
# Configure Jira connection values in .env, then:
.\scripts\run_windows.ps1
```

Open `http://127.0.0.1:5000/login`.

For the durable Sprint Viewer, a worker process must run while `SPRINT_VIEWER_MODE=snapshot`. `scripts/run_windows.ps1` manages it automatically for local Windows use. A first request imports Jira data into scoped SQLite snapshots; later requests read the completed snapshot from SQLite after a fresh Jira access check. Core tickets publish first while history, comments, and the five existing metric searches continue independently.

Production uses Python 3.12, a local file-backed SQLite database in WAL mode, Waitress behind TLS, and exactly one supervised worker. See `deploy/waitress.md`. Automatic age-based Jira freshness remains deferred; `Refresh Sprints` refreshes only the sprint catalog.

Production installation uses the matching runtime hash lock: `requirements/runtime-py312-windows.lock` or `requirements/runtime-py312-linux.lock`, always with `--require-hashes`. The root `requirements.txt` remains a local development compatibility entry point.

## Important Docs

- First-time setup: `docs/first_time_setup.md`
- Environment variables: `docs/env_reference.md`
- Route map: `docs/routes.md`
- Architecture: `docs/architecture.md`
- Operations and logging: `docs/operations.md`
- Hardening implementation ledger: `docs/hardening/status.md`

## Development Rules

- Keep existing compatibility routes working while adding canonical routes.
- Move one feature at a time into `app/features`.
- Add or update tests before changing behavior.
- Never commit `.env`, logs, SQLite databases, or PAT values.
