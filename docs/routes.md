# Route Map

## Canonical User Routes

- `/dashboard`
- `/auth/login`
- `/auth/signup`
- `/auth/signup/confirm`
- `/auth/signup/set-password`
- `/auth/forgot-password`
- `/settings/integrations`
- `/settings/projects-boards`
- `/settings/tableau-custom-views`
- `/automation/rule-copier`
- `/automation/sprint-viewer`
- `/reports/tci`

## Canonical API Routes

- `/api/automation/rule-copier/fetch`
- `/api/automation/rule-copier/copy`
- `/api/automation/sprint-viewer/sprints`
- `/api/automation/sprint-viewer/issues`
- `/api/automation/sprint-viewer/metrics`
- `/api/automation/sprint-viewer/snapshots/<snapshot_id>/status`
- `/api/automation/sprint-viewer/snapshots/<snapshot_id>/issues`
- `/api/automation/sprint-viewer/snapshots/<snapshot_id>/components/<component>`
- `/api/automation/sprint-viewer/snapshots/<snapshot_id>/retry`
- `/api/automation/sprint-viewer/snapshots/<snapshot_id>/authorize`
- `/api/automation/sprint-viewer/snapshots/<snapshot_id>/export-manifest`
- `/api/reports/tci/link-details`
- `/api/session/status`
- `/api/session/extend`
- `/api/client-log`

## Compatibility Routes

The previous routes remain registered during migration:
- `/home`
- `/login`
- `/signup`
- `/signup/confirm`
- `/signup/set-password`
- `/forgot-password`
- `/config/integrations`
- `/config/projects`
- `/config/custom-views`
- `/tableau/custom-views`

New code should use canonical routes. Existing URLs remain available to avoid breaking bookmarks and deployed frontend code.

When `SPRINT_VIEWER_MODE=snapshot`, the issues and metrics POSTs may return HTTP 202 with `snapshot_id`, `view_id`, component states, and `retry_after_ms`. Status GETs are read-only and never enqueue work. A report component is returned only after its report view passes the configured live Jira access check.

Health routes are `/health/live`, `/health/ready`, and `/health/worker`.
