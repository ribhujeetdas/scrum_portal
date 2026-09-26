# Sprint Viewer — past sprint analysis preview

Scope revision: 13 September 2026. This feature covers closed sprints only. The former active workspace, toggle and script have been removed. Historical developer contribution and developer-at-close grouping remain. This README supersedes earlier active-sprint walkthroughs.

- [Interactive review](http://127.0.0.1:8794/designs/sprint-viewer-v2/index.html?view=Team#overview)
- [Implementation plan and GPT-sol handoff](../../plans/sprint-viewer-v2.md)
- [Role comparison and review walkthrough](REVIEW.md)

## Run the preview

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File docs/designs/sprint-viewer-v2/start-preview.ps1
```

The launcher reuses or starts a hidden background Python server bound to 127.0.0.1:8794, serving only the docs folder. It prints the Overview URL. Run it again after a restart; use `-Port 8795` if necessary. You can also open `index.html` directly, but localhost gives more predictable browser storage.

The default URL opens closed Sprint 24 and Overview directly. Legacy `#active` links normalize to `#overview`. There is no active-sprint sample or switch in the running preview.

## Reviewable functionality

One page-level View as changes Team, Developer, PO / BA, Scrum Master and Engineering Manager analyses. The four leading role measures and supporting evidence sections differ; the five shared sprint totals stay fixed. Shared Flow & Quality, Trends and Retrospective remain available to all roles. See REVIEW.md for the expected numbers and interpretation.

Working controls include selected developer, explicit Issue focus, historical grouping, search/sort/pagination, metric and suggestion evidence filters, issue drawer, filtered CSV, role URL restoration, rule explanations and role prompts. Goal assessments, notes, actions and dismissals persist only in this browser. Reset preview edits removes these local records. No messages or Jira writes occur.

This is a synthetic 29-issue sample: 24 original, 5 added, 21 completed, 6 unfinished and 2 removed. All point estimates are 2 in the fixture. Cycle durations, preceding sprint aggregates, explicit goal links, acceptance and scope reasons are illustrative inputs. Missing contributor, capacity, interval and release evidence remains unavailable. No AI service or runtime dependency exists.

## Production boundaries and field catalogue

No production application code, route, database, Jira data or configuration has been changed by this proposal. The complete plan covers normalized event history, real APIs, authorized revisions, role calculations, server persistence, migrations, validation and rollout.

The user will provide a separate Jira field catalogue; it is pending. Plan section 16 defines exact-name/ID resolution, payload shape validation, normalization, history matching, per-metric dependencies, versioning and unavailable states. Section 17 is the self-contained GPT-sol implementation handoff and includes a copyable prompt. Do not infer deployment mappings from synthetic sample-data.js.

## Files and reference precedence

- `index.html`, `preview.css`, `role-review.css`, `sample-data.js`, `role-review.js`, `preview.js`: current standalone prototype.
- `start-preview.ps1`: local preview launcher.
- `REVIEW.md`: current role review and expected sample results.
- The implementation plan is authoritative for production behavior and latest scope.
- Older concept/screenshot PNGs and `concept-prompts.md` are historical visual references. Some show superseded navigation or earlier layouts; do not use them to reintroduce an active workspace or override current scope. The current executable preview is the visual source for this handoff.

## Validation scope

The previous role revision exercised five role compositions, exact evidence/CSV membership, role URL persistence, human record persistence, keyboard tab navigation and drawer focus. This scope revision removes the active runtime and checks default/legacy URLs, all roles and historical interactions again. See the latest verification record below. Production Python/integration suites have not been run for these documentation-only/application-prototype changes; prescribed production checks are in plan section 17.

### Closed-sprint scope verification — 13 September 2026

Environment: localhost docs server, existing Playwright Chromium, 1440×1000 and 390×844. Browser plugin/`browser` skill was unavailable; the frontend testing skill's Playwright path was used without installing dependencies.

| Check | Result |
| --- | --- |
| Default and legacy URLs | Pass — closed Sprint24/Overview, `#active` normalizes to `#overview` |
| Active workspace removal | Pass — no toggle, section or active runtime request |
| Meaningful page / error overlay | Pass — correct page, visible controls, no error overlay |
| All role compositions / shared totals | Pass — five roles, four distinct leading measures per role, fixed team totals |
| Historical developer evidence | Pass — Alex11 issues and historical grouping; clear restores29 |
| Acceptance evidence / CSV | Pass — PAY-216 and PAY-218 only; PAY-217 excluded |
| Suggestion evidence | Pass — four review issues despite previous role-specific focus |
| Responsive layout | Pass — all roles at1440px/390px, no page overflow; mobile closed-sprint label given additional width |
| Console | Pass — no page errors, console errors or warnings in tested flow |
| Syntax / whitespace | Pass — all three current JavaScript files parse; diff check clean |

Current screenshots were visually inspected and saved outside the repository under the user's Codex visualizations directory (`sprint-review-past-only`). This validates the static proposal, not live Jira mappings, server closed-sprint enforcement, history reconstruction, production authorization or migrations. Those remain the implementing agent's required checks.
