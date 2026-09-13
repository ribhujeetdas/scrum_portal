# Environment Reference

Use `.env.example` as the source of truth for local configuration.

Required for normal application use:
- `APP_ENV`
- `SECRET_KEY`
- `DATABASE_URL`
- `FERNET_KEY`
- `JIRA_BASE_URL`
- `JIRA_AUTOMATION_ACTOR_ACCOUNT_ID`
- `JIRA_PAT_VALIDATION_CACHE_SECONDS`
- `EXTERNAL_HTTP_TIMEOUT_SECONDS`
- `EXTERNAL_HTTP_RETRY_TOTAL`
- `EXTERNAL_HTTP_RETRY_BACKOFF_SECONDS`
- `EXTERNAL_HTTP_RETRY_STATUS_CODES`
- `EXTERNAL_CA_BUNDLE`, `EXTERNAL_TRUST_ENV` (enterprise CA and approved proxy environment support)
- `TABLEAU_BASE_URL`
- `JIRA_SOURCE_ID`
- `JIRA_ENABLED`, `TABLEAU_ENABLED`
- `SPRINT_VIEWER_MODE` (`direct` or `snapshot`)
- `SPRINT_SNAPSHOT_ACCESS_POLICY` (`jira_revalidate`)
- `TRUSTED_HOSTS`

Security:
- `SESSION_COOKIE_SECURE`
- `REMEMBER_COOKIE_SECURE`
- `SESSION_COOKIE_SAMESITE`
- `SESSION_TIMEOUT_MINUTES`
- `SESSION_WARNING_THRESHOLD_RATIO`
- `LEGACY_ROUTE_DEPRECATION_HEADERS`
- `LEGACY_ROUTE_SUNSET`
- `TRUSTED_PROXY_COUNT`
- `RATE_LIMITS_ENABLED`

Logging:
- `LOG_LEVEL`
- `LOG_DIR`
- `LOG_FILE`
- `LOG_BACKUPS`
- `LOG_TO_CONSOLE`
- `LOG_TIMEZONE`
- `LOG_FORMAT`
- `LOG_WERKZEUG_LEVEL`
- `LOG_URLLIB3_LEVEL`
- `LOG_SQLALCHEMY_LEVEL`

Diagnostics:
- `TRACE_SPRINT_VIEWER`
- `TRACE_JIRA_JQL`
- `TRACE_SPRINT_VIEWER_API`
- `TRACE_SPRINT_VIEWER_UI`
- `SPRINT_METRICS_MAX_WORKERS`

Durable Sprint Viewer and SQLite worker:
- `SPRINT_VIEWER_SNAPSHOT_USER_IDS`
- `SPRINT_JOB_LEASE_SECONDS`, `SPRINT_JOB_HEARTBEAT_SECONDS`, `SPRINT_JOB_MAX_ATTEMPTS`
- `SPRINT_JOB_POLL_SECONDS`, `SPRINT_WORKER_STALE_SECONDS`
- `SPRINT_COMPONENT_MAX_RUNTIME_SECONDS`
- `JIRA_MAX_INFLIGHT_PER_SOURCE`, `JIRA_MAX_BACKGROUND_INFLIGHT`
- `JIRA_HISTORY_VISIBILITY_FOLLOWS_ISSUE` (leave `false` unless the capability probe confirms issue visibility safely governs history)
- `SQLITE_BUSY_TIMEOUT_MS`, `SQLITE_WRITE_BUDGET_SECONDS`

Bounded transport:
- `HTTP_CONNECT_TIMEOUT_SECONDS`, `HTTP_READ_TIMEOUT_SECONDS`
- `HTTP_OPERATION_BUDGET_SECONDS`, `HTTP_RETRY_AFTER_MAX_SECONDS`
- `HTTP_MAX_JSON_BYTES`
- `TABLEAU_MAX_CSV_BYTES`

Keep tracing disabled in production unless you are actively investigating a problem.
# Sprint Viewer v2 configuration

`SPRINT_VIEWER_V2_ENABLED=false` retains the existing viewer. Set it to `true` with `SPRINT_VIEWER_MODE=snapshot` to select the v2 template for the existing snapshot user allowlist. `SPRINT_VIEWER_FIELD_MAPPING_FILE` is an absolute or application-working-directory-relative JSON path. See `docs/config/sprint-viewer-fields.example.json` and `docs/plans/sprint-viewer-v2-implementation.md`.

The registry allows only named parsers and explicit field IDs. A validated instance mapping takes precedence over the three legacy Jira field settings; scoped board/project overrides are applied to the frozen historical registry. Overlapping overrides at the same specificity are rejected. Entries restricted to other scopes/types remain unavailable/not applicable. Mapping changes create a new v2 series key and preserve prior reports and private review records.

Workflow status IDs, population-discovery validation, calendar settings and optional daily-event validation belong in the JSON's `analysis_config`. Catalogue photos alone do not establish those settings. The fixed deployment timezone defaults to Asia/Kolkata. Other IANA zones require timezone data on the host. No AI or new network service is required.

For exact startup commands and UI troubleshooting, see [Run Sprint Viewer v2](sprint-viewer-v2-run.md). Both mode and flag are required; a nonempty user allowlist limits eligible accounts. Restart web and worker after changing configuration.

With no mapping file, the supplied photo IDs for points, membership, application and feature are used with strict runtime parsers (`photo_confirmed`). Explicit mapping files replace this default; `pending` entries are not extracted. This does not enable history access or infer workflow status IDs.
