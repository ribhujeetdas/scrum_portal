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
# Sprint Viewer v2 routes

The existing Sprint Viewer routes remain compatible. With v2 enabled, granted report reads use `/automation/sprint-viewer/views/<view_id>/`:

| Method | Suffix | Purpose |
|---|---|---|
| GET | `analysis` | Frozen historical metrics, role descriptors, coverage and current private review context |
| GET | `issues` | Exact evidence/filter cohort, stable sorting, 25-row pages |
| GET | `issues/<issue_id>/timeline` | Authorized boundary fields and event pages (`event_page`, 100 events) |
| GET | `suggestions` | Versioned rules and prerequisite coverage |
| GET | `trends` | Bounded already-authorized comparable reports; no Jira imports |
| GET | `export` | Same server-resolved filters, CSV provenance and formula escaping |
| GET | `record-history` | Private append-only history (`record_key`, `page`) |
| POST | `records` | Validated assessment/action/disposition/issue-review/context write with expected revision and idempotency |

Reads use `revision` where applicable. Issue queries allow `focus`, `developer`, `search`, `evidence`, `feature`, `application`, `issue_type`, `status`, `sort` and `page`. Evidence references cannot select records outside the authorized revision. Expired grants return 403 and conflicts return 409. Human writes use the application's existing CSRF protection.

The compatibility issue-admission POST additionally accepts `rebuild: true` for an explicit candidate generation and `snapshot_id` for reauthorizing a pinned owned historical generation. Both retain board/sprint ownership checks. Non-closed saved sprint inputs return `sprint_not_closed`.
