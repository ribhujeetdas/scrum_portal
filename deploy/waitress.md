# Waitress deployment

Run the web application and Sprint Viewer worker as two supervised processes on the same host and under the same service account. Both processes must read the same environment file and use the same absolute SQLite path. The database must be on a local persistent disk; network shares and synchronized folders are unsupported.

Before first start or after deploying migrations, stop both processes, create a verified backup, and run:

```powershell
python -m pip install --require-hashes -r requirements\runtime-py312-windows.lock
```

Use `requirements/runtime-py312-linux.lock` on Linux. Then run:

```powershell
flask setup-db --check
flask setup-db --apply
flask check-db
```

Start the web process behind the organization's TLS reverse proxy:

```powershell
waitress-serve --listen=127.0.0.1:8080 --threads=8 wsgi:app
```

Start exactly one supervised worker process:

```powershell
python -m workers.sprint_import_worker
```

The supervisor must set the repository as its working directory, use the virtual environment executables, restart failed processes with bounded backoff, and send a graceful termination before force-kill. Verify `/health/live`, `/health/ready`, and `/health/worker` before routing traffic or enabling `SPRINT_VIEWER_MODE=snapshot`.
