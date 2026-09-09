# First-Time Setup Guide

## Windows ZIP Extraction

Repository paths are limited to 60 characters and checked in CI for Windows-invalid or reserved names. GitHub's archive directory and the directory selected for extraction are added to that length. Extract the download to a short local path such as `C:\src\scrum_portal`; avoid deeply nested OneDrive, SharePoint, Desktop, or email-attachment directories. The repository check reserves 120 characters for the selected parent path and 60 characters for GitHub's archive directory while staying below the legacy 260-character Windows limit.

## Automated Windows Setup

From PowerShell in the repository root, run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_windows.ps1
```

The script creates a Python 3.12 virtual environment, installs the hash-locked dependencies, creates `.env`, generates `SECRET_KEY` and `FERNET_KEY`, configures a local file-backed SQLite database, applies migrations, verifies database integrity, runs the smoke check, and runs the test suite. Existing valid secrets and explicit database configuration are preserved. Use `-RegenerateSecrets` only when intentionally invalidating existing encrypted PAT data and sessions; use `-SkipTests` to omit the full test suite.

The script discovers Python through the Windows `py` launcher or a Python 3.12 `python.exe` on `PATH`. When necessary, pass an explicit interpreter, for example `-Python312 C:\Python312\python.exe`.

The script intentionally leaves Jira, Jira custom fields, Jira PATs, and optional Tableau settings for manual configuration. A Jira PAT belongs to a user and is entered during signup or through Settings, never in the bootstrap script.

Start both the web process and the worker with:

```powershell
.\scripts\run_windows.ps1
```

The launcher starts the worker as a hidden child process when snapshot mode is enabled, starts the web server in the current window, and stops its child worker when the web server exits. Worker output is written under `logs/`.

## 1. Create A Virtual Environment

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install --require-hashes -r requirements\dev-py312-windows.lock
```

## 2. Create `.env`

Copy `.env.example` to `.env` and replace every placeholder. Generate `FERNET_KEY` with:

```powershell
py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Never commit `.env`, database files, or logs.

## 3. Initialize Or Upgrade The Database

```powershell
flask setup-db --check
flask setup-db --apply
flask check-db
```

`setup-db` safely distinguishes an empty database, a known versioned database, an exact unversioned legacy-head schema, and an unknown/partial schema. Direct `flask db upgrade` rejects an empty database. Adopting an exact unversioned legacy database requires `--adopt-legacy-head --backup-reference <verified-backup>`.

## 4. Run Verification

```powershell
py -m pytest
py scripts\smoke_check.py
```

## 5. Start The App

```powershell
py wsgi.py
```

Open `http://127.0.0.1:5000/login`.

For manual startup in snapshot mode, start a second terminal with `py -m workers.sprint_import_worker`, set `SPRINT_VIEWER_MODE=snapshot`, and restart the web process. The Windows launcher above manages both local processes automatically.

On Linux use `requirements/dev-py312-linux.lock`. Production installs the corresponding `runtime-py312-*.lock`; do not install the development manifest into the service environment.
