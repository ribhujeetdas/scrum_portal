# Sprint Viewer v2 implementation ledger

Implemented 13 September 2026 against `sprint-viewer-v2.md`. The existing Flask/Jinja/vanilla JavaScript and SQLite worker remain in place. The older viewer is the default until the feature flag is enabled. No Jira writes or AI dependencies were added.

## Field catalogue

Source: the user's **Photo 1.jpg–Photo 4.jpg** attachments. Exact attachment filenames and SHA-256 digests are in [`../config/sprint-viewer-fields.example.json`](../config/sprint-viewer-fields.example.json). That file is a relevant-field subset of the photos, not a claim that every photographed field is needed.

| Logical concept | Photo field | Jira ID | State |
|---|---|---|---|
| Baseline/entry points | story_points | customfield_10106 | ID confirmed by photo; existing default matches; deployment parser/history pending |
| Sprint membership | sprint | customfield_10104 | ID confirmed; object-array current parser and raw numeric-list history adapter implemented; deployment shape pending |
| Application | application_name | customfield_11700 | ID confirmed; existing default matches; option shape/history pending |
| Feature relation | feature_link | customfield_10100 | ID confirmed; existing default matches; relation semantics/history pending |
| Team | team | customfield_10200 | ID confirmed; schema/context pending |
| Acceptance criteria | acceptance_criteria | customfield_10601 | ID confirmed; criteria text is **not** an Accepted state |
| Explicit flag | flagged | customfield_10900 | ID confirmed; option semantics pending; not automatically treated as a blocker |
| Work category | work_activity_category | customfield_12003 | ID confirmed; option-to-category semantics pending |
| Work classification | work_classification | customfield_15804 | ID confirmed; semantics pending |
| Target dates | target_start / target_end | customfield_10202 / customfield_10203 | ID confirmed; date-only versus timestamp shape pending |
| Goal association / acceptance outcome | No definitive mapping supplied | Unresolved | Private human issue-review records implemented |
| Done / active / review / blocked states | No workflow status IDs supplied | Unresolved | Must be explicitly configured; no display-name guesses |
| Cut-off field | rationale_to_skip_user_acceptance_testing | Unknown | **Skipped**: no existing project references and not required by this feature |

Photographs establish identifiers, not the deployed Jira version, metadata permissions, response schemas, historical completeness, plugin semantics or option meanings. No live deployment validation was performed and no private Jira data was used as a test fixture. The example intentionally marks custom entries `pending`; changing them to `validated` is a deployment configuration decision after checking sanitized payloads.

## Implemented surface

| Area | Behavior |
|---|---|
| Closed-only admission | Saved non-closed sprints rejected on issue/metric routes and repository admission; v2 core imports recheck the closed board catalogue |
| Evidence | Immutable history component carries normalized events and boundary projections; discovers removed issues from all existing metric memberships; core remains independently usable |
| Calculations | Original/added/final-removed partitions, already-Done exclusions, count and fixed-point lenses, partial point coverage, scope overlap, reopened work, cycle median/P85, age and clipped status-stage durations |
| Rules | All ten rules with explicit prerequisite coverage; current overdue actions separate from sprint-close rules; repeated carryover and variation use authorized comparable history |
| Authorization | Existing scope/epoch/owner/session/grant checks; v2 historical access also requires metric access; revision-bound evidence, detail and CSV reads; expiry clears UI |
| Review | Append-only private assessment, action, context, observation disposition and issue goal/acceptance/scope records; server timestamps, expected revision, idempotency and conflict responses; retained across generations |
| UI | Five distinct roles, five shared tabs, count/points lens, developer selection, shared server-paginated issue table, filters/sort/grouping, exact evidence replacement, paginated drawer, keyboard tabs, native dialogs and responsive layout |
| Trends | Bounded already-authorized preceding reports, matching board/configuration and similar duration, selected sprint excluded; median throughput, range/MAD and median of sprint ratios; no silent imports |
| Export | Server resolves the same filters and evidence, includes revision/role/time-basis metadata and escapes spreadsheet formulas |
| Compatibility | Original viewer and routes retained; configured story-point history matching corrected without mutating raw input |

## Source limitations and rollout gates

The supported Release A/B paths are implemented, but deployment readiness is **not** established by the automated fixtures. Do not mark an unresolved mapping validated just to enable a metric.

- Jira version, metadata permissions, field shapes, option semantics and representative source reconciliation remain pending. Scoped board/project and type restrictions are supported; automatic metadata discovery is not performed. The user-supplied IDs are preserved without guessing display-name matches.
- Only complete expanded changelogs are supported. Truncated/legacy sprint-history shapes remain unavailable; no unsupported pagination endpoint is assumed. Configure `population_discovery_validated` only after checking the deployed ScriptRunner discovery against known removed/re-added examples. Historical issue-type changes require additional type mapping and conservatively suppress exact historical populations.
- All ten rule paths exist. Repeated carryover requires the immediately preceding comparable authorized report; delivery variation requires at least five preceding comparable reports; current overdue-action observations are labelled separately from sprint-close facts. Daily scope/Done/WIP tables require `daily_events_validated` and WIP status mappings. None of these are enabled by the photos alone.
- Trends and previous actions read bounded, already-authorized reports; they do not silently import or grant access to historical reports. A short baseline is explained. Open the required preceding closed reports before expecting comparison coverage.
- External contributor activity, imported acceptance outcomes, requirement-change history, numerical capacity and escaped defects require independent sources. Human acceptance/goal/scope/context records are stored and displayed separately from frozen Jira metrics. Criteria text is never treated as acceptance.
- Grouping is explicitly per server page. Full filter/sort controls, URL selection/filter restoration, pinned snapshot reauthorization, review audit history and explicit conflict reconciliation are provided. Summary text is labelled as collected text in the drawer; no historical estimate/status fallback is hidden.
- Sprint-window comment counts have their own grant and readiness state. Normalized events are retained inside immutable per-issue history JSON rather than a separate event warehouse. Large-report performance, production Jira reconciliation and the role-user pilot still require deployment measurements.

## Configuration, migration and rollback

1. Back up the database using the existing operations procedure. Apply migrations using the established `setup-db --apply`/deployment workflow. New additive revision: `d48e6b9c0d03`, following `b27d5f8a9c02`; creates `sprint_review_records` and its scope/revision/idempotency indexes. No user database was migrated during implementation.
2. Copy `docs/config/sprint-viewer-fields.example.json` to a deployment-owned configuration path. Validate the required fields against authorized Jira metadata and sanitized current/changelog examples. Record verified `known_status_ids`, `done_status_ids`, `active_status_ids`, `review_status_ids`; blocked status IDs are optional. Set calendar version, timezone, working weekdays and holidays for calendar rules.
3. Set `SPRINT_VIEWER_FIELD_MAPPING_FILE` to that JSON path. The three existing `JIRA_*_FIELD` variables remain backward compatible; validated instance registry fields take precedence. Mapping/configuration and legacy input changes alter the v2 query version. Existing reports retain their frozen configuration.
4. Use `SPRINT_VIEWER_MODE=snapshot`, run the existing supervised worker, then enable `SPRINT_VIEWER_V2_ENABLED=true` for the existing snapshot user allowlist. Historical access still requires `JIRA_HISTORY_VISIBILITY_FOLLOWS_ISSUE=true` only where deployment permissions justify it.
5. Import/rebuild a closed sprint and reconcile evidence before expanding access. Rebuild uses a candidate generation while the previous UI report stays usable. Review records survive rebuilds.
6. Roll back by disabling `SPRINT_VIEWER_V2_ENABLED`; retain the additive table and old generations. The migration's downgrade deliberately preserves human records; do not use it as a destructive rollback script.

## Verification

Tests added before the initial behavior changes cover core historical boundaries, raw immutability, changed estimate IDs, missing/invalid/zero values, remove/re-add and added-removed overlap, creation within sprint, clipped stage intervals, trend baselines, authorization expiry, exact evidence/CSV membership, review idempotency/conflicts and closed-only admission.

Rendered Chromium tests use the actual Flask page and database-backed analysis/review endpoints with mocked Jira catalog/import status. They exercise all roles, shared totals, drawer/Escape, assessment and action saves, 1440px desktop and 390px mobile, and runtime errors. Screenshots are temporary pytest artifacts outside the repository. Existing browser coverage also exercises the compatibility viewer.

Final verification: `.venv/Scripts/python.exe -m pytest -q` — **109 passed** in 22.80 seconds. Three existing Flask-SQLAlchemy `get_engine` deprecation warnings remain in the migration environment. `node --check` passed for both viewer entry scripts, and `git diff --check` passed. The rendered test checks the whole document for overflow at 390px, rather than only the inner table region. Source validation and performance/pilot gates above are not implied by these automated tests.
