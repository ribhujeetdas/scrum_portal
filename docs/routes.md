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
