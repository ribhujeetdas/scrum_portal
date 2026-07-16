# Environment Reference

`.env.example` is the complete, versioned template. `.env` is untracked and must be backed up through the installation's secret-management procedure, separately from SQLite backups.

## Required production identity

- `APP_ENV=production` enables fail-closed validation.
- `APPLICATION_VERSION` identifies the manually deployed release in logs and health responses.
- `SECRET_KEY` must be a non-placeholder value of at least 32 bytes.
- `FERNET_KEY` must be a valid Fernet key and must remain stable or stored PATs cannot be decrypted.
- `DATABASE_URL` must be a file-backed `sqlite:///...` URL.
- `JIRA_BASE_URL` and `TABLEAU_BASE_URL` must be absolute HTTP(S) origins without embedded credentials.

## SQLite and capacity

- `SQLITE_JOURNAL_MODE=DELETE` is the cross-platform safe default. WAL is accepted only on explicitly fixed SQLite versions.
- `SQLITE_SYNCHRONOUS=FULL`, busy timeout, write retry, backup retention, and minimum free disk settings protect durability and predictable failure behavior.
- `DATABASE_INSTANCE_LOCK=true` enforces the supported one-process topology.
- Waitress thread and connection limits bound concurrent work. Sprint workers, outbound bulkheads, operation page/deadline budgets, circuit thresholds, and rate limits prevent one integration or user from exhausting the process.

## Sprint metrics

`SPRINT_METRICS_MODE=queued` is the supported mode. A maximum of two process-wide
workers execute ScriptRunner queries and checkpoint each result in SQLite; HTTP
request threads only create jobs and return status. Read timeouts are not retried
automatically, avoiding timeout-and-retry amplification. Successful closed-sprint
results are cached per user because Jira PAT permissions can differ.

`SPRINT_METRICS_MODE=legacy` is a temporary rollback option. It restores the old
synchronous, per-request calculation and should only be used while diagnosing a
queued-mode regression. The `SPRINT_METRICS_MAX_WORKERS` and
`SPRINT_METRICS_HTTP_TIMEOUT_SECONDS` settings apply to that legacy path.

## Sessions

`SESSION_TIMEOUT_MINUTES` is the renewable idle window. `SESSION_ABSOLUTE_MAX_MINUTES` cannot be extended. Cookies are HTTP-only and SameSite-protected. Set the two `*_COOKIE_SECURE` values to `true` only if the deployed endpoint actually uses HTTPS; secure cookies are not sent over plain HTTP.

## Logs

`LOG_FILE` contains structured application/request events. `AUDIT_LOG_FILE` separately records successful authentication, credential, configuration, automation, report export, backup, restore, and migration actions. Both rotate by day and retain the configured number of files.

Client-supplied trace IDs are stored as `client_request_id`; the server always generates the authoritative `request_id`.

## Diagnostics

Keep all `TRACE_*` values false normally. Enable only the smallest relevant trace for a time-boxed investigation, then disable it. Trace logging never authorizes logging PATs, passwords, CSRF values, or full response bodies.
