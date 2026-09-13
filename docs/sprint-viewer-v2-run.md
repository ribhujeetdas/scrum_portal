# Run Sprint Viewer v2

## Upgrade an existing Windows checkout

Use Python 3.12. Stop the existing web process and worker first (Ctrl+C in the Windows launcher stops its child worker). Run these commands from the repository root, on `feature/production-hardening-implementation`:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
# Before upgrading an existing database; choose a new backup name each time.
.\.venv\Scripts\python.exe -m flask --app wsgi:app backup-db --destination data\before-sprint-v2.db
.\scripts\run_windows.ps1 -SprintViewerV2
```

The launcher runs setup, installs the Windows development hash lock, applies migrations, and starts the web and worker with the same configuration. Do not use `-SkipPreflight` on the first run after an upgrade. The additive migration `d48e6b9c0d03` creates the review-record table. For a fresh checkout with no database, omit the backup command; the launcher creates the environment and database.

Open <http://127.0.0.1:5000/automation/sprint-viewer> and sign in. Configure Projects & Boards in Settings if redirected there. The heading should read **Past sprint analysis**, even before selecting data. Choose a project, board, and closed sprint, then click **Analyze**. No analysis runs when the page opens or when a selection changes. Role controls and report tabs appear after the report loads. `-ProductionStyle` uses port 8080 instead.

## Persistent or manual startup

Set these values in the repository `.env`:

```dotenv
SPRINT_VIEWER_MODE=snapshot
SPRINT_VIEWER_V2_ENABLED=true
```

Leave `SPRINT_VIEWER_SNAPSHOT_USER_IDS` empty for all authenticated users, or include the intended local user IDs in the comma-separated allowlist. An account outside that list sees the original viewer. The `-SprintViewerV2` switch does not change the allowlist or save configuration to `.env`; it sets process environment values inherited by both children. Environment variables already set in PowerShell or a service manager take precedence over `.env`. Restart both processes after changes.

For manual startup, after a backup and dependency installation:

```powershell
.\.venv\Scripts\python.exe -m flask --app wsgi:app setup-db --check
.\.venv\Scripts\python.exe -m flask --app wsgi:app setup-db --apply
.\.venv\Scripts\python.exe -m flask --app wsgi:app check-db
.\.venv\Scripts\python.exe wsgi.py
```

In another terminal at the same repository root, run `.\.venv\Scripts\python.exe -m workers.sprint_import_worker`. Run only one worker. Both processes need the same database, keys, and feature configuration.

## Dependencies and data configuration

V2 uses the existing Flask, SQLite, Jinja and vanilla JavaScript stack. No npm install or frontend build is required. No dependency or lock update is needed for this feature. Windows setup installs `requirements/dev-py312-windows.lock`; production uses the matching `requirements/runtime-py312-*.lock` with `--require-hashes`. The root `requirements.txt` remains the unlocked development compatibility entry point.

`SPRINT_VIEWER_FIELD_MAPPING_FILE` is optional. Without it, the viewer uses the supplied photo IDs for points (`customfield_10106`), sprint membership (`customfield_10104`), application (`customfield_11700`) and feature (`customfield_10100`); existing `JIRA_*_FIELD` overrides are respected. `photo_confirmed` enables strict shape-checked extraction without claiming workflow/history validation. An explicitly configured file replaces these defaults and can disable entries with `pending`. To configure historical analysis, copy [the example](config/sprint-viewer-fields.example.json) to a deployment-owned JSON file and set this variable to its absolute path. Keep unverified mappings pending. Photo-confirmed field IDs alone do not establish workflow status IDs, complete histories or discovery correctness. Some metrics will therefore show unavailable coverage until validation is complete. Follow the [mapping and rollout ledger](plans/sprint-viewer-v2-implementation.md). Leave `JIRA_HISTORY_VISIBILITY_FOLLOWS_ISSUE=false` unless deployment permissions justify enabling that capability; it is not a UI toggle.

Summary cards can use the original viewer's authorized ScriptRunner results when reconstructed history is unavailable. These cards say **Jira sprint query**; their point values are collected estimates, not baseline estimates. Issue values labelled **at collection** are also separate from historical values. Missing historical cohorts, including unfinished-at-close, remain unavailable when they cannot be established.

## Troubleshooting

| Symptom | Check |
|---|---|
| Original UI | Both mode and v2 flag, allowlist membership, and restart of the correct web process. Check the launcher's UI-selection message. |
| Redirect to Settings | Add an enabled project and board for the signed-in account. |
| New heading but no report | Select a closed sprint and click **Analyze**, check the user PAT in Settings, and confirm the worker is running. |
| Import stays pending | Checks back off and pause after two minutes; **Analyze** checks again without forcing a rebuild. Inspect `logs/worker-dev.stderr.log`, `logs/worker-dev.stdout.log`, and `/health/worker`. |
| Missing review table/schema error | Stop processes, back up, and run `setup-db --apply`; `setup-db --check` should report revision `d48e6b9c0d03`. |
| Historical metrics unavailable | Check history permission, changelog completeness and validated mapping/workflow coverage; enabling the UI does not validate Jira data. |
| Old report data | Use **Rebuild analysis** after configuration changes. **Refresh sprint list** only refreshes the catalogue. |
| Old assets after restart | Hard-refresh the browser (Ctrl+F5); ensure the URL/port points to this checkout. |

Rollback: set `SPRINT_VIEWER_V2_ENABLED=false` and restart both processes. Retain the additive database table and review records.
