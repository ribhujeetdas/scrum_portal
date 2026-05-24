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
- `app/logging_conf.py`: structured request and application logging.
- `app/static/js/app.js`: shared request ID, toast, client logging, and session timeout behavior.

Handled service failures should use `log_handled_exception(...)` instead of ad hoc `logger.warning(...)` calls when the exception traceback helps diagnose an external API, database, or integration failure. Keep the response body user-safe and put operational details in structured log context.

Jira/Tableau-facing services should use `ExternalHttpClient` for retries, timeouts, HTTP error snippets, JSON parsing, and normalized external API failure events. Feature API routes should prefer `json_ok(...)` and `json_error(...)` so response shape and request IDs stay consistent.

Event names should be stable and feature-scoped:
- External HTTP failures: `<service>.request.failed`
- External JSON parse failures: `<service>.response.invalid_json`
- Handled feature failures: `<area>.<feature>.<operation>_failed`

## Performance Notes

Sprint lists are cached in `user_board_sprints` per user and board. Sprint issue and metric calls still execute on demand because they depend on current Jira sprint state; do not persist those results without a freshness policy. If issue/metric latency becomes high, add a background job table keyed by `user_id`, `board_id`, `sprint_id`, and an explicit `refreshed_at`, then have the UI poll a canonical `/api/...` job endpoint.

Jira PAT ownership validation is cached for `JIRA_PAT_VALIDATION_CACHE_SECONDS` within the user session. Keep this short-lived; it avoids repeated `/myself` calls during multi-step UI flows while still revalidating after token/user/session changes.

## Migration Rule

Do not move multiple features in one change. Move one feature, keep the old URL surface working, run full tests, then proceed to the next feature.
