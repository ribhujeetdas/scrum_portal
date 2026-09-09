# Architecture Guide

## Current Direction

The application is moving from blueprint-only organization toward feature-based organization. During migration, existing blueprints remain active so URLs, endpoint names, tests, and templates keep working.

## Feature Boundaries

Each card or major workflow should have a clear home:

- Rule Copier: `app/features/automation/rule_copier`
- Sprint Viewer: `app/features/automation/sprint_viewer`
- Projects & Boards settings: `app/features/settings/projects_boards`
- Integrations settings: `app/features/settings/integrations`
- Tableau custom view settings: `app/features/settings/tableau_custom_views`
- TCI reports: `app/features/reports/tci`

Existing blueprints still own URL registration, login decorators, and endpoint names for compatibility. Migrated route behavior now lives in feature packages for Projects & Boards, Tableau Custom View settings, Rule Copier, Sprint Viewer, and TCI reports.

Canonical user-visible links should point at `/dashboard`, `/auth/...`, `/settings/...`, and `/reports/tci`. Legacy URLs such as `/home`, `/login`, `/config/...`, and `/tableau/custom-views` remain registered temporarily as compatibility wrappers only.

## Shared Infrastructure

- `app/core/api.py`: consistent JSON success/error responses with request IDs and sanitized details.
- `app/core/config_validation.py`: startup configuration checks.
- `app/core/error_logging.py`: standardized handled-exception logging with stack traces and safe diagnostic context.
- `app/core/http_client.py`: reusable external HTTP client with retries, timeouts, sanitized snippets, and structured service errors.
- `app/core/jira_pat_validation.py`: short-lived session cache for Jira PAT identity validation, keyed by user, email, and PAT hash.
- `app/core/dependencies.py`: shared app-context factories for crypto and external service clients.
- `app/core/database.py`: SQLite WAL, foreign-key, busy-timeout, synchronous-write, and NullPool policy.
- `app/core/security.py`: server-side auth sessions plus user, credential, and access epochs.
- `app/core/rate_limits.py`: SQLite-backed cross-process request limits.
- `app/features/automation/sprint_viewer/models.py`: scoped immutable snapshot components, jobs, grants, leases, and idempotency records.
- `workers/sprint_import_worker.py`: one supervised process with one core/access lane and two enrichment lanes.
- `app/logging_conf.py`: structured request and application logging.
- `app/static/js/app.js`: shared request ID, toast, client logging, and session timeout behavior.

Handled service failures should use `log_handled_exception(...)` instead of ad hoc `logger.warning(...)` calls when the exception traceback helps diagnose an external API, database, or integration failure. Keep the response body user-safe and put operational details in structured log context.

Jira/Tableau-facing services should use `ExternalHttpClient` for retries, timeouts, HTTP error snippets, JSON parsing, and normalized external API failure events. Feature API routes should prefer `json_ok(...)` and `json_error(...)` so response shape and request IDs stay consistent.

Event names should be stable and feature-scoped:
- External HTTP failures: `<service>.request.failed`
- External JSON parse failures: `<service>.response.invalid_json`
- Handled feature failures: `<area>.<feature>.<operation>_failed`

## Sprint Viewer Data Flow

Sprint catalogs and completed reports are durable SQLite data. A report series is scoped by portal user, Jira source, credential/access epochs, board, sprint, and calculation/query/schema versions. On a miss, the web process creates one candidate and one deduplicated core job. The worker publishes a complete core revision first, then history, comments, five metric memberships, and final derived metrics as immutable revisions. The active generation changes only after required components are complete and optional components are terminal.

Every new display or export grant revalidates Jira identity, board/sprint membership, all core and metric issue IDs, and stored comment visibility. History is withheld unless the deployment explicitly confirms that history visibility follows issue visibility. Completed report reads then come from SQLite. There is no automatic time-based freshness in this release.

SQLite is intentionally single-host: web and worker processes share one absolute local file, WAL permits readers during a writer, and writes remain short. Leases and fence values reject stale worker publication. Four source request slots reserve two for core/access work and cap enrichment at two.

Jira PAT ownership validation is cached for `JIRA_PAT_VALIDATION_CACHE_SECONDS` within the user session. Keep this short-lived; it avoids repeated `/myself` calls during multi-step UI flows while still revalidating after token/user/session changes.

## Migration Rule

Do not move multiple features in one change. Move one feature, keep the old URL surface working, run full tests, then proceed to the next feature.
