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

## Run Sprint Viewer v2

The v2 UI is opt-in. Pulling the code or running setup does **not** enable it in an existing `.env`. Stop the running web and worker processes, then run:

```powershell
.\scripts\run_windows.ps1 -SprintViewerV2
```

The launcher installs the locked dependencies, applies database migrations, and starts both processes with v2 enabled. Back up an existing database before upgrading; see [the v2 run guide](docs/sprint-viewer-v2-run.md). Open `http://127.0.0.1:5000/automation/sprint-viewer` after login. Add Projects & Boards in Settings if prompted, then select a closed sprint and click **Analyze**. The new page has role selection and Overview, Suggestions, Flow & Quality, Trends, and Retrospective tabs.

For persistent activation or manual/service startup, set `SPRINT_VIEWER_MODE=snapshot` and `SPRINT_VIEWER_V2_ENABLED=true` in `.env`, then restart **both** processes. A nonempty `SPRINT_VIEWER_SNAPSHOT_USER_IDS` restricts the new view to those local user IDs. The launcher option preserves that restriction.

No new Python packages, npm installation, or frontend build are required for v2. The field mapping file is optional for displaying the UI; verified Jira history/workflow configuration is needed for historical metrics. See [configuration and troubleshooting](docs/sprint-viewer-v2-run.md).

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
