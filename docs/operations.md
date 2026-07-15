# Operations, Logging, and Traceability

## Health and startup

- `GET /health/live` confirms that the process can serve requests.
- `GET /health/ready` checks SQLite connectivity, foreign-key enforcement, migration head, log-directory writability, and free disk. A non-ready process returns 503.
- `scripts/run_server.py` repeats critical checks before Waitress starts and holds an advisory lock for the life of the process. A second process fails immediately.
- `scripts/diagnose.py` emits a sanitized configuration and runtime report. It never prints secret values.

## Logs

`logs/app.log` contains JSON application and request records. `logs/audit.log` is a separate rotating audit trail. Records include the server `request_id`, optional untrusted `client_request_id`, method, path without query data, endpoint, status, duration, authenticated user identifiers, stable event name, and sanitized exception context.

The response `X-Request-ID` is server-generated and authoritative. If a client supplied an ID, the response exposes it separately as `X-Client-Request-ID` and logs it only as supporting context.

External events use sanitized endpoint paths and fields such as `external_service`, `external_operation`, `external_status_code`, category, retryability, and duration. Redirects and cross-origin absolute URLs are rejected before credentials can be forwarded.

## Trace a failure

1. Capture `X-Request-ID` from the failed response or UI message.
2. Search `app.log` for the exact JSON `request_id`.
3. Start at `request.complete` to confirm route, status, and duration.
4. Review earlier records with the same ID, especially feature-scoped handled failures and adjacent `<service>.request.failed` events.
5. Use the exception stack only from the log. User responses intentionally contain a generic message and request ID.
6. Never paste PATs, passwords, session cookies, CSRF tokens, `.env`, or full upstream bodies into an incident record.

## Routine checks

Before deployment and after dependency changes run `python scripts/verify.py`. Daily operational checks should include `python scripts/check_db.py`, readiness status, free disk, backup age, and application/audit log rotation. Run `python scripts/diagnose.py` when startup or readiness fails.

Backups, restores, journal changes, and schema migrations are covered by [SQLite operations](sqlite_operations.md). Manual release steps are covered by [Manual deployment](manual_deployment.md).
