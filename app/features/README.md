# Feature Package Map

This folder groups code by user-facing workflow. Blueprints still register existing URLs and endpoint names, while migrated route behavior lives in these feature packages.

Ownership:
- `automation/rule_copier`: Jira automation rule copy workflow.
- `automation/sprint_viewer`: Sprint and quality metric workflow.
- `settings/integrations`: Jira and Tableau credential settings.
- `settings/projects_boards`: Jira project and board settings.
- `settings/tableau_custom_views`: Tableau custom view mapping settings and related settings forms.
- `reports/tci`: TCI report viewing and Jira link validation.

Do not move shared infrastructure here. Shared logging, config, HTTP clients, and security helpers belong in `app/core` or `app/shared`.
