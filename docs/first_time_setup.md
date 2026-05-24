# First-Time Setup Guide

## 1. Create A Virtual Environment

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

## 2. Create `.env`

Copy `.env.example` to `.env` and replace every placeholder. Generate `FERNET_KEY` with:

```powershell
py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Never commit `.env`, database files, or logs.

## 3. Initialize Or Upgrade The Database

```powershell
flask db upgrade
```

For a brand-new local database:

```powershell
flask init-db
flask db upgrade
```

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
