# Sprint Viewer — role analysis review

13 September 2026 · Revised interactive proposal · Synthetic data · No AI dependency

Open the [interactive review](http://127.0.0.1:8794/designs/sprint-viewer-v2/index.html?view=Team#overview). If the server is stopped, run `start-preview.ps1` from this folder. The complete [implementation plan](../../plans/sprint-viewer-v2.md) now includes the role specification in section 5, metric contracts in section 6, and production gates in sections 12–17.

## What changed

The earlier role controls only filtered tickets and reordered suggestions. One page-level **View as** selector now changes Overview headings, four leading measures, role-specific evidence sections, initial issue focus and suggestion discussion prompts. Shared sprint totals stay fixed. Flow & Quality, Trends and Retrospective remain shared tools accessible from every role.

**Past sprint analysis is the entire feature.** The preview opens directly into closed Sprint 24, with no active workspace or mode switch. Historical developer contribution/grouping remains. No production application code or Jira data was changed. This scope supersedes earlier active-sprint proposals.

## Compare the views

| View | New information visible in the preview | Decision supported |
| --- | --- | --- |
| Team | Added work completion; cycle median; repeated carryover; goal-linked unfinished; contribution table; scope reasons and work mix | Agree what remains and what the team should follow up |
| Developer | Selected person's closing assignments, completed/unfinished work, full-issue cycle median and aged unfinished tickets | Inspect assigned work and next steps with its historical context |
| PO / BA | Goal-linked delivery, recorded acceptance, Done-but-pending acceptance, sprint-scoped feature delivery and changes missing reasons | Review intended scope, acceptance and remaining business work |
| Scrum Master | Cycle median, review queue, repeated carryover, unfinished age and current improvement actions | Prepare a retrospective and assign follow-up |
| Engineering Manager | Original-plan completion, throughput baseline, scope movement, cycle P85, multi-sprint comparison, work mix and contribution context | Discuss consistency and support needs with evidence |

## A 10–15 minute walkthrough

1. **Confirm closed-sprint scope.** Open the preview without a hash. It shows closed Sprint 24 and Overview directly, with no active/past switch. The sprint selector contains one closed sample intentionally. Historical developer contribution is available under Team/Developer/Engineering Manager; use Group by developer at close in the issue table.

2. **Start with Team.** The fixed summary is 24 planned, 75% original-plan completion, 21 total completed, 6 unfinished, +5 added / −2 removed. Under the tabs, the Team analysis shows 3/5 added work completed, 5-day median cycle, 2 repeated carryover issues and 2 goal-linked unfinished issues. Click one measure: the issue table should show the metric's evidence and retain the Team role.

3. **Review developer contribution.** Alex has 11 retained closing assignments: 7 completed and 4 unfinished. Priya has 9: 7 completed and 2 unfinished; one additional item was removed. Sam has 7, all completed; one additional item was removed. All three happen to have 7 completed items in this fixture, hence 33.3% each after rounding. These are closing-assignment shares of 21 completed tickets, not shares of effort. Click a developer or completed/unfinished count to inspect those tickets. Removed assignments use identity at removal and are not included in closing-scope totals.

4. **Switch to Developer.** Alex is the default sample selection; choose Priya or Sam. The four measures, contribution row, follow-up table and issue focus update together. Sam has no unfinished closing work, so an explicit empty state appears. The cycle metric is full issue elapsed time, including waits and work by other people. Collaboration, pairing and review credit are not invented from ticket ownership.

5. **Switch to PO / BA.** Expect 10/12 goal-linked items completed; 13/19 retained stories accepted; 2 Done stories awaiting acceptance; 2 changed issues without recorded reasons. Click pending acceptance: PAY-216 and PAY-218 are the exact two stories. PAY-217 is a Task and is excluded. The feature table covers only sprint scope. In scope changes, PAY-226 and PAY-229 have no recorded reason. The goal remains Not assessed until you save a human assessment.

6. **Check the meaning of scope change.** Scope moved from 24 to 27 retained issues: 24 + 5 − 2. Gross movement is 7/24 = 29.2%, net growth is 3/24 = 12.5%, and additions/removals remain separate. This fixture has no remove/re-add loop or estimate changes. The plan defines those cases separately, including overlap when an added issue is later removed.

7. **Switch to Scrum Master.** Expect 5-day completed cycle median, four issues in review at close, and two issues unfinished at two consecutive closes. Inspect the aging table: the oldest unfinished item is 15 days old at close. One item is blocked, but blocked duration is unavailable. Open Suggestions, inspect Why this appears, create an action with an owner/date, then return to Overview: the open-action count reflects your current browser records.

8. **Switch to Engineering Manager.** Expect 75% original-plan completion, throughput21 versus prior median20, gross movement29.2%, cycle P85 of6 days. The preceding five throughput values range19–23. Selected Sprint24 is excluded from its own baseline. Capacity and real post-release defect evidence remain unavailable, so no capacity-normalized score or escaped-defect rate is shown.

9. **Check shared controls.** Change roles while on Suggestions: priority and the labelled discussion prompt change, while rule facts/evidence stay the same. Click View4 issues for the review queue: all four appear even in PO/BA view, because evidence replaces incompatible Story-only filtering. Clear filters keeps the role. Export CSV and confirm it contains only the currently filtered ticket population with role/time-basis metadata.

10. **Check manual records.** Save a goal assessment or action; reload to confirm local browser persistence. The role also restores through `?view=`. Use Reset preview edits to remove this preview's notes/actions/dispositions. Other filter/developer URL restoration, shared persistence and edit-conflict handling are production work.

## Metric definitions to agree on

| Topic | Proposed default | Why it matters |
| --- | --- | --- |
| Predictability | Original-plan completion plus comparable throughput/cycle distributions and scope context | A single score would conceal different causes and denominators |
| Scope | Distinct added, final removed, gross movement and net growth; repeated membership events separately | A stable net can hide substantial change |
| Contribution | Closing-assignee counts and start/entry estimates; other contributors shown only from explicit evidence | Closing owner does not represent all work performed |
| Time | Elapsed calendar time; completed cohort separated from unfinished age | Cycle time is not working effort and must not omit unfinished context |
| Acceptance | Explicit acceptance state, separate from Done | Workflow completion does not establish stakeholder approval |
| Outcome | Human goal assessment with recorded evidence | Ticket completion alone cannot establish business outcome |
| Missing evidence | Unavailable or a labelled measured subset; never zero-filled | Metrics must communicate their limits |

## Working now versus planned

**Working in the review:** five distinct Overview lenses, one global role selector, selected-developer analysis, contribution/feature/scope/aging/trend tables, metric-to-issue drill-down, explicit issue focus, role-aware suggestion prompts, issue drawer, filtered CSV, manual goal assessment and action records, historical developer grouping, role deep links and mobile layout.

**Illustrative sample inputs:** cycle durations, historical sprint aggregates, consecutive-close markers, goal linkage, story acceptance and scope reasons. Counts and role cohorts derive from the shared fixture. These samples do not establish live Jira source availability.

**Production work:** normalized event ingestion and boundary reconstruction, server authorization/audit/storage, actual sprint navigation, configured goal/acceptance sources, complete assignment/contributor histories, capacity/dependency records, daily WIP and burnup, estimate movement, team-shared actions, actual release/defect linkage, all filter URL restoration, report versioning and production-scale performance validation. The plan defines these without claiming they exist in the preview.

## Questions for this design review

- Does each role now answer a genuinely different question in the first analysis section?
- Is closing-assignee context the right default for contribution, with optional historical contribution evidence later?
- Do PO/BA users need acceptance per story, per feature, or both in the first production release?
- Which Jira fields reliably represent goal links, blockers, technical debt and scope reasons in this deployment?
- Should human assessments/actions initially be private or shared with the authorized team?

These are review topics, not blockers to inspecting the prototype. The implementation plan includes conservative defaults and source-discovery gates.

## Implementation handoff

Give GPT-sol the [complete plan](../../plans/sprint-viewer-v2.md) and your separate Jira field catalogue. Section 16 specifies field ID resolution, shapes, normalizers, history mappings and unavailable states. Section 17 contains the execution order, file touchpoints, verification commands and a copyable implementation prompt. The field file is pending; no new deployment field IDs have been invented.
