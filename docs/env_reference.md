# Environment Reference

Use `.env.example` as the source of truth for local configuration.

Required for normal application use:
- `SECRET_KEY`
- `DATABASE_URL`
- `FERNET_KEY`
- `JIRA_BASE_URL`
- `JIRA_AUTOMATION_ACTOR_ACCOUNT_ID`
- `TABLEAU_BASE_URL`

Security:
- `SESSION_COOKIE_SECURE`
- `REMEMBER_COOKIE_SECURE`
- `SESSION_COOKIE_SAMESITE`
- `SESSION_TIMEOUT_MINUTES`
- `SESSION_WARNING_THRESHOLD_RATIO`

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

Keep tracing disabled in production unless you are actively investigating a problem.
