# Architecture Guide

## Deployment boundary

The application intentionally supports one Python/Waitress process, multiple Waitress threads, and one file-backed SQLite database on Windows or Linux. Scaling is bounded vertical concurrency within that process. Multiple processes, shared-disk SQLite, and multiple hosts are unsupported because in-memory rate limits, circuit state, write serialization, and SQLite locking are process-local.

## Structure

The repository uses a pragmatic feature-first layout without a disruptive wholesale rewrite. Compatibility blueprints continue to register stable endpoint names; behavior lives in feature packages. Shared cross-cutting infrastructure lives in `app/core`, persistence models remain centralized, and operational commands live in `scripts`.

## Feature Boundaries

Each card or major workflow should have a clear home:

- Rule Copier: `app/features/automation/rule_copier`
- Sprint Viewer: `app/features/automation/sprint_viewer`
- Projects & Boards settings: `app/features/settings/projects_boards`
- Integrations settings: `app/features/settings/integrations`
- Tableau custom view settings: `app/features/settings/tableau_custom_views`
- TCI reports: `app/features/reports/tci`

Existing blueprints own URL registration and endpoint compatibility. Migrated behavior now lives in feature packages for Integrations, Projects & Boards, Tableau Custom View settings, Rule Copier, Sprint Viewer, and TCI reports.

Canonical user-visible links should point at `/dashboard`, `/auth/...`, `/settings/...`, and `/reports/tci`. Legacy URLs such as `/home`, `/login`, `/config/...`, and `/tableau/custom-views` remain registered temporarily as compatibility wrappers only.

## Shared Infrastructure

- `app/core/api.py`: consistent JSON success/error responses with request IDs and sanitized details.
- `app/core/config_validation.py`: startup configuration checks.
- `app/core/database.py`: SQLite pragmas, serialized/retried writes, health, migration status, and single-instance locking.
- `app/core/datetime_utils.py`: normalized timezone-aware integration timestamps.
- `app/core/error_logging.py`: standardized handled-exception logging with stack traces and safe diagnostic context.
- `app/core/http_client.py`: strict-origin external HTTP, timeouts, idempotent retries, bulkheads, circuit breaking, pagination budgets, and sanitized errors.
- `app/core/jira_pat_validation.py`: short-lived session cache for Jira PAT identity validation, keyed by user, email, and PAT hash.
- `app/core/rate_limit.py`: bounded per-process protection for authentication and expensive operations.
- `app/core/security.py`: browser security headers and content policy.
- `app/core/dependencies.py`: shared app-context factories for crypto and external service clients.
- `app/logging_conf.py`: structured request and application logging.
- `app/static/js/app.js`: shared request ID, toast, client logging, and session timeout behavior.

Handled service failures should use `log_handled_exception(...)` instead of ad hoc `logger.warning(...)` calls when the exception traceback helps diagnose an external API, database, or integration failure. Keep the response body user-safe and put operational details in structured log context.

Jira/Tableau-facing services should use `ExternalHttpClient` for retries, timeouts, HTTP error snippets, JSON parsing, and normalized external API failure events. Feature API routes should prefer `json_ok(...)` and `json_error(...)` so response shape and request IDs stay consistent.

Event names should be stable and feature-scoped:
- External HTTP failures: `<service>.request.failed`
- External JSON parse failures: `<service>.response.invalid_json`
- Handled feature failures: `<area>.<feature>.<operation>_failed`

## Persistence and concurrency

All mutations use `execute_write`, which serializes writes within the process, applies a bounded lock retry, and guarantees rollback. Every SQLite connection enables foreign keys, a busy timeout, and configured synchronous durability. DELETE journaling is the default; WAL is rejected on SQLite builds affected by the WAL reset defect. The database instance lock prevents an accidentally duplicated server process.

Schema changes use Alembic. `scripts/migrate_db.py` initializes fresh schemas or takes a verified safety backup before upgrading an existing schema. Sprint integration timestamps are stored as real datetime columns rather than arbitrary strings.

## Performance notes

Sprint lists are cached in `user_board_sprints` per user and board. Sprint issues
remain request-driven so the fast Jira details render first. ScriptRunner metrics
run through the process-local coordinator in
`app/features/automation/sprint_viewer/metric_jobs.py`; query checkpoints, partial
results, and per-user cache expiry are stored in `user_sprint_metric_runs`. The UI
polls canonical status endpoints, so slow Jira work never occupies a Waitress
request thread.

Jira PAT ownership validation is cached for `JIRA_PAT_VALIDATION_CACHE_SECONDS` within the user session. Keep this short-lived; it avoids repeated `/myself` calls during multi-step UI flows while still revalidating after token/user/session changes.

The Sprint page uses eager-loaded boards to avoid per-project queries. Metrics use
two process-wide workers rather than matching the Waitress thread count. The
ScriptRunner circuit is isolated from normal Jira issue/profile calls, read timeouts
are not automatically retried, and each job has a bounded deadline. External
pagination retains page and elapsed-time limits.

## Migration rule

Move one feature boundary at a time, keep compatibility wrappers thin, and prove behavior through the local verification gate. A larger restructure is not warranted while the current boundaries remain testable and dependency direction stays feature -> service/core -> persistence.
