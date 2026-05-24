# Scrum Portal

Flask application for Jira automation support, sprint reporting, Tableau custom view mapping, and TCI report workflows.

## Quick Start

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
flask db upgrade
py -m pytest
py scripts\smoke_check.py
py wsgi.py
```

Open `http://127.0.0.1:5000/login`.

## Important Docs

- First-time setup: `docs/first_time_setup.md`
- Environment variables: `docs/env_reference.md`
- Route map: `docs/routes.md`
- Architecture: `docs/architecture.md`
- Operations and logging: `docs/operations.md`

## Development Rules

- Keep existing compatibility routes working while adding canonical routes.
- Move one feature at a time into `app/features`.
- Add or update tests before changing behavior.
- Never commit `.env`, logs, SQLite databases, or PAT values.
