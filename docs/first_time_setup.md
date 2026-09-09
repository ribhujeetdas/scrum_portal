# First-Time Setup Guide

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

To test snapshot mode, start a second terminal with `py -m workers.sprint_import_worker`, set `SPRINT_VIEWER_MODE=snapshot`, and restart the web process.

On Linux use `requirements/dev-py312-linux.lock`. Production installs the corresponding `runtime-py312-*.lock`; do not install the development manifest into the service environment.
