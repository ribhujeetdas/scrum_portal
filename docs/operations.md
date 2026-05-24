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

## Troubleshooting 500s

1. Capture the `X-Request-ID` from the browser network tab or UI logs.
2. Search `logs/app.log` for that request ID.
3. Review `event`, `endpoint`, `user_id`, `eid`, `exception`, and external service error messages.
4. If the failure is in Jira or Tableau, check the sanitized external API response body and HTTP status.

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
