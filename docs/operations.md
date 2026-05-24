# Operations And Logging

## Logging

Logs are JSON by default and include request correlation fields:
- `request_id`
- `method`
- `path`
- `endpoint`
- `status_code`
- `duration_ms`
- `user_id`
- `eid`

Every frontend request should send `X-Request-ID`. The backend returns the same header on responses.

External Jira/Tableau failures include:
- `event`: normalized as `<service>.request.failed` or `<service>.response.invalid_json`
- `external_service`: `jira` or `tableau`
- `external_operation`: HTTP method and path
- `external_endpoint`: Jira/Tableau endpoint path
- `external_status_code`
- `external_response_snippet`: sanitized response body snippet

Handled feature failures use stable event names, for example:
- `automation.rule_copier.copy_failed`
- `automation.sprint_viewer.issues_failed`
- `settings.projects.board_list_failed`
- `settings.tableau_custom_views.validate_failed`
- `reports.tci.csv_failed`
- `reports.tci.link_details_failed`

## Trace By X-Request-ID

1. Capture the `X-Request-ID` from the browser network tab or UI logs.
2. Search `logs/app.log` for `"request_id":"<id>"`.
3. Start with the final `request.complete` record to confirm `path`, `endpoint`, `status_code`, and `duration_ms`.
4. Review earlier records with the same `request_id`, especially `event`, `feature`, `operation`, `user_id`, `eid`, and `exception`.
5. If Jira or Tableau failed, inspect `external_service`, `external_operation`, `external_status_code`, and `external_response_snippet`.
6. Use `client.event`, `fetch.http_error`, or `fetch.network_error` records to connect browser-side failures to the same request flow.

## Troubleshooting 500s

1. Follow the request ID trace above.
2. Check the `exception` field for the Python stack trace.
3. For handled integration failures, check both the feature event and any adjacent `<service>.request.failed` event.
4. Do not paste PATs, tokens, or passwords into tickets. Logs redact known secret patterns, but tickets should still contain only request IDs and sanitized snippets.

## Production Defaults

Recommended production values:

```text
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_TO_CONSOLE=false
LOG_WERKZEUG_LEVEL=WARNING
LOG_URLLIB3_LEVEL=WARNING
LOG_SQLALCHEMY_LEVEL=WARNING
TRACE_SPRINT_VIEWER=false
TRACE_JIRA_JQL=false
TRACE_SPRINT_VIEWER_API=false
TRACE_SPRINT_VIEWER_UI=false
SESSION_COOKIE_SECURE=true
REMEMBER_COOKIE_SECURE=true
```
