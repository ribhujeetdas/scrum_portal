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

## Shared Infrastructure

- `app/core/api.py`: consistent JSON success/error responses with request IDs and sanitized details.
- `app/core/config_validation.py`: startup configuration checks.
- `app/core/error_logging.py`: standardized handled-exception logging with stack traces and safe diagnostic context.
- `app/core/http_client.py`: reusable external HTTP client with retries, timeouts, sanitized snippets, and structured service errors.
- `app/core/dependencies.py`: shared app-context factories for crypto and external service clients.
- `app/logging_conf.py`: structured request and application logging.
- `app/static/js/app.js`: shared request ID, toast, client logging, and session timeout behavior.

Handled service failures should use `log_handled_exception(...)` instead of ad hoc `logger.warning(...)` calls when the exception traceback helps diagnose an external API, database, or integration failure. Keep the response body user-safe and put operational details in structured log context.

Jira/Tableau-facing services should use `ExternalHttpClient` for retries, timeouts, HTTP error snippets, and JSON parsing. Feature API routes should prefer `json_ok(...)` and `json_error(...)` so response shape and request IDs stay consistent.

## Migration Rule

Do not move multiple features in one change. Move one feature, keep the old URL surface working, run full tests, then proceed to the next feature.
