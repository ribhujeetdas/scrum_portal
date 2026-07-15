# Manual Deployment Runbook

This project is deployed manually and has no GitHub Actions or hosted pipeline. Every release is therefore gated by a reproducible local verification report.

## 1. Prepare the release

1. Confirm the intended branch and cleanly review `git status` and `git diff`.
2. Build a source-only release archive from the reviewed commit:

   ```text
   git archive --format=zip --output scrum-portal-release.zip HEAD
   ```

   Extract it into a short installation path such as `C:\scrum_portal` or
   `/opt/scrum_portal`. Do not copy `.git`, `.venv`, `.worktrees`, Python
   caches, logs, backups, or local database files. Recreate the virtual
   environment on the target operating system.
3. Create or activate a Python 3.12 virtual environment.
4. Install runtime dependencies with `python -m pip install --require-hashes -r requirements.txt`. Use `requirements-dev.txt` on the verification machine.
5. Preserve the existing `.env`; compare it with `.env.example` and add new settings explicitly.
6. Run `python scripts/verify.py`. Keep `artifacts/verification/latest.json` with the release record, but do not commit it.

## 2. Stop and protect data

Stop the existing server and confirm its process has exited. Run:

```text
python scripts/check_db.py
python scripts/backup_db.py
```

Copy the reported backup and its JSON metadata to the installation's protected backup location. Do not proceed if integrity, foreign-key, or checksum validation fails.

## 3. Deploy and migrate

Replace application code while preserving `.env`, `instance/`, `logs/`, and `backups/`. Then run:

```text
python scripts/migrate_db.py
python scripts/database_configure.py
python scripts/diagnose.py
```

`migrate_db.py` takes an additional safety backup for an existing schema. Review every command's non-zero exit as a failed release.

## 4. Start and verify

Start `python scripts/run_server.py` from the repository root using the installation's normal service account. Check `/health/live`, then `/health/ready`. Verify login, one read-only Jira operation, and one read-only Tableau operation with a non-administrator test account where available.

Monitor `app.log` and `audit.log` for startup, migration, authentication, SQLite lock, external circuit, and unexpected 5xx events.

## Rollback

Stop the server. Restore the pre-release code. If the schema or data changed, run:

```text
python scripts/restore_db.py --backup <verified-backup.sqlite3> --confirm
python scripts/check_db.py
```

The restore command validates the supplied checksum and database, takes a safety backup of the current database, atomically replaces the file while holding the instance lock, and validates the result. Start the previous code only after its expected schema is restored.
