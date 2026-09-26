# Sprint Viewer v2 — product, UX and implementation plan

Status: implementation handoff specification, revised 13 September 2026. Scope: past/closed sprint analysis only. Includes five role views, contribution context, scope analysis and predictability. The user-supplied Jira field catalogue is pending; section 16 defines how to bind and validate it. No production integration is part of this documentation/preview deliverable.

Companion: [interactive design preview](../designs/sprint-viewer-v2/index.html). All preview data is synthetic. Its local edits belong only to the preview browser. The preview demonstrates the design; it does not establish Jira data availability or production metric correctness.

**Implementation handoff:** this document is the complete product/engineering contract. Read sections 1–6 for behavior and metrics, 7–15 for rules/architecture/validation, **16 for the user-supplied Jira field catalogue**, and **17 for the implementation sequence, payload contracts, commands and copyable GPT-sol prompt**. The catalogue supplements field semantics and deployment mappings; it does not reintroduce excluded feature scope. No knowledge of earlier chat turns is required.

## 1. Product decision

**This feature handles past (closed) sprint analysis only.** Open directly into the closed-sprint review. Do not implement an Active sprint section, active/past workspace switch, current-assignment board, active-sprint API path or live ticket refresh for this feature. Developer contribution and developer grouping refer to the selected past sprint at close/removal. Other project features are outside this change.

This scope is the latest user correction and supersedes all earlier active-sprint proposals, screenshots and conversation history. The implementation agent must follow this document and the supplied Jira field catalogue; older design artifacts are not additional requirements.

No model, AI API, chatbot, embeddings, inference service or AI runtime dependency. Calculations are deterministic Python functions; suggestions are versioned rules with fixed message templates. Goal assessments, causal explanations and improvement decisions are human input. Do not infer business value, individual performance, sentiment, root causes or goal achievement from ticket activity.

Primary jobs:

1. A developer selects a closed sprint, reviews developer-wise historical assignments and contribution context, and inspects completed/unfinished work, status at close, baseline estimates, feature, recorded waits and sprint-window comments.
2. A PO/BA checks delivered capabilities, changes to the plan and remaining goal-related work.
3. A scrum master prepares a retrospective using verifiable exceptions and follows up prior actions.
4. An engineering manager compares delivery consistency, quality and team constraints across comparable sprints.

Success criteria: users can explain a metric, find its issues, distinguish a recorded fact from a team explanation, and identify the next action without opening several reports. Validate these tasks with representatives of all four roles before rollout.

## 2. Current implementation and constraints

Inspected sources: `app/templates/automation/sprint_viewer.html`, `app/static/js/sprint_viewer.js`, `app/services/sprint_viewer_service.py`, `app/features/automation/sprint_viewer/{calculations,models,jobs,routes,repository}.py`, `docs/architecture.md` and `readme.md`.

| Existing capability | Reuse / change |
| --- | --- |
| Flask/Jinja, Bootstrap and JavaScript | Keep the stack. No SPA migration or large dashboard framework. |
| Project/board/sprint selection and report export | Keep compatible routes; improve navigation and export provenance. |
| Scoped snapshots, immutable component revisions, jobs, grants, leases | Extend these mechanisms, preserving authorization and atomic publication. |
| Core, history, comments and metric components | Retain independent readiness. Tickets remain usable during enrichment. |
| Five metric membership categories | Useful baseline, but historical estimates and set overlaps require correction. |
| Reconstructed closing status, assignee and points | Extend to timestamped field evidence and event sequences. Existing stored history rows contain extracted values, not a complete event warehouse. |
| Current-point metric sums | Never present these as start-of-sprint estimates. Introduce explicit time bases and a new calculation version. |
| Multiple-sprint membership used for one carryover statistic | Replace with boundary-based carry-in, carry-out and consecutive carryover definitions. |
| Developer accordion and comment totals | Reuse historical developer grouping and canonical identity. Retain relevant fields in the past issue table/drawer: key, summary, type, status at close, baseline points, feature and sprint-window comments with coverage. Contribution totals use close/removal identity. Comment counts remain context, not performance scores. |
| SQLite WAL and one supervised worker | Keep short transactions, bounded enrichment concurrency and pagination. No infrastructure expansion required initially. |

The current history worker marks incomplete expanded changelog responses unavailable; it does not promise to paginate arbitrary Jira Data Center history. Confirm supported endpoints and permissions against the deployed Jira version before selecting an adapter. Snapshot storage alone cannot recover historical fields that Jira never recorded.

## 3. Scope and sequencing

### Release A: closed-sprint review foundation

- Closed sprint selection and direct Overview entry; no workspace mode switch.
- Historical developer grouping, contribution context and Unassigned/unknown identities.

- Compact selectors, previous/next closed sprint, preserved selection in URL.
- Goal text plus optional manual assessment and note.
- Five summary measures with count/point switch, visible definitions and coverage.
- Plan-outcome bar and added-work breakdown; no invented daily chart without history.
- Shared issue table, issue drawer, filters, search, grouping and export.
- One page-level View as selector with distinct Team, Developer, PO / BA, Scrum Master and Engineering Manager analysis. Required role sections must have explicit unavailable states when enrichment is not ready; role switching cannot merely reorder identical cards.
- Closing-assignee contribution table, sprint-scoped feature delivery, distinct scope additions/removals, and human-entered goal links, acceptance and scope reasons. Import structured acceptance evidence when the Jira field mapping is available.
- Suggestions tab with review queue, late additions and repeated carryover where prerequisites exist.
- Retrospective action records and optional structured explanations.
- Explicit loading, unavailable, partial and denied states.

### Release B: flow and comparable history

- Persist normalized status, estimate, sprint-membership and blocked events.
- Cycle time, closing age, stage time, reopened issues, daily WIP and burnup.
- Last 6–8 comparable closed sprints, with samples, coverage and configuration versions.
- Team capacity/context notes, configurable calendar and rule settings.

### Release C: optional integrations

- Deployment/release links and linked escaped defects with a defined observation window.
- External acceptance-system evidence and requirement-change tracking if structured fields exist. Basic manual acceptance/goal evidence belongs in Release A.
- Delivery-system metrics only with their required integration and independent definitions.

Explicit exclusions: individual productivity rankings, comment-count scores, inferred effort from points, automatic goal grading, composite health scores, causal claims from correlations, AI-generated narratives and automatic Jira writes.

## 4. Information architecture and screen specification

### Shared shell and closed-sprint selection

Keep the portal navigation. Show a compact project/board/closed-sprint/export header and a Past sprint analysis label. The only analysis tabs are Overview, Suggestions, Flow & Quality, Trends and Retrospective. The page-level View as selector governs role analysis. Do not show an active/past mode selector.

Reuse `fetch_closed_sprints_for_board` and preserve `state=closed`. Restore a valid authorized closed-sprint deep link; otherwise restore the last valid selection or select the most recently completed accessible sprint. If none is available, show **No closed sprints available** and keep project/board selectors usable. Reject non-closed sprint IDs in report creation/import and validate source state rather than relying only on UI filtering. Reuse the application's safe error envelope for `sprint_not_closed`. If a previously closed sprint is reopened, do not refresh it as an eligible closed report; preserve previously published evidence only under existing access and label its captured revision/state.

The existing catalog limits results to current/prior calendar years by start date. Preserve this compatibility default for the initial UI and explain the range. Trends must explicitly show a shortened baseline when the range excludes history. A later explicit year-range option must bound imports; do not silently request all historical sprints or change the legacy route contract.

Show scheduled dates, actual close date when different, and timezone. Switching project/board/sprint clears incompatible filters, cancels stale requests and uses the selected report revision consistently for issue details and exports. Current field values must never become historical values without reconstruction or a clearly labelled detail-only fallback.

Historical developer grouping includes key, summary, issue type, closing status, start/entry estimate, feature key and sprint-window relevant-comment context. Optional columns use the same historical coverage rules as other metrics. Group by canonical principal and include Unassigned/unknown identities. There is no current-assignment board in this feature.

**Refresh sprint list** refreshes the closed catalog only. **Rebuild analysis**, when authorized, creates a candidate historical revision and keeps the last complete generation usable until replacement publication. It is not live ticket refresh. Role changes and table filters trigger no Jira imports. Timelines/comments/trends load independently; historical issues remain usable while enrichment is pending.

### Past sprint review header

Below the heading, show goal text and optional assessment. Default is **Not assessed**. Manual assessment dialog: Achieved / Partially achieved / Not achieved / Not assessed; note; evidence URL; author and saved time. Never preselect Achieved from completion percentage. Assessment can be corrected with audit history.

Use one flat five-column summary strip:

1. Planned: original issue count and start estimates.
2. Plan completed: original completion ratio, numerator and denominator.
3. Total completed: original plus added work completed by close and retained in closing scope.
4. Unfinished at close: retained original plus added work, unfinished at close.
5. Scope change: additions and removals displayed separately, never only their net.

Default to issue counts for robust readability. Offer points as an explicit lens with estimation coverage and basis. Missing history must not silently become zero. Metric buttons filter the common issue table and announce the changed results.

### Overview

One page-level View as selector precedes the shared summary. Below the tabs, Overview starts with a role-specific heading, four leading measures and one or two relevant evidence sections described in section 5. Shared original-plan outcome and discussion panels follow; the common issue table remains available below. Keep long secondary content collapsible in production, without concealing missing-data messages. The five shared sprint totals never change silently when the role changes.

Optional daily burnup appears after event coverage is sufficient; its absent state is not a fabricated flat line. Avoid showing several charts with the same story.

### Suggestions — the new proposed view

Purpose: help prepare discussion without making diagnoses. Title **Suggestions**; subtitle **Recorded facts and optional next steps**. Show Open / Action created / Dismissed views and category filter. Counts refer to the current filters. A compact availability strip explains which rules could not run.

Each row/panel contains:

- Plain factual title, e.g. **4 issues were awaiting review at sprint close**.
- Evidence count, time basis and category, not an unexplained risk score.
- Fixed explanation of why the observation may be useful.
- Optional prompt, e.g. **Review these items together and record any shared constraint.**
- **View 4 issues**, **Create action**, and **Dismiss** controls.
- Expandable **Why this appears**: rule ID/version, predicate, configured threshold, sample size, coverage and calculation time.

Evidence opens an exact membership-filtered table. A title count must equal its issue count for the report revision and permissions. Create action opens a prefilled, editable form; user chooses owner and date and saves. A suggestion is not automatically an action. Dismiss requires an optional reason and can be undone. Refreshing data must not silently reopen a dismissed identical observation.

No results: **No observations matched the enabled rules.** This does not assert a healthy sprint. Missing data: **2 rules could not be evaluated — view data coverage.** Do not mix this with a zero-result state. Severity, if later needed, must be team-configured attention priority rather than a judgment of team quality.

### Flow & Quality

Cycle time median/P85 and sample size; review/testing time; unfinished age at close; reopen count; recorded blocked duration. A simple horizontal stage-time chart plus evidence table. Describe durations as elapsed calendar time initially, not working effort. Add business-time mode only with a configured timezone/calendar.

The completed cohort excludes work already Done before the sprint, removed work and unfinished work. Unfinished age is a separate distribution to avoid survivor bias. Blocking may overlap review/testing; do not sum overlapping durations as if they were disjoint. No percentage-based flow efficiency unless active/waiting states are explicitly mapped.

### Trends

Default six closed sprints on the same board. Small aligned series for original-plan completion, completed issue count, scope additions/removals and cycle time. Supply accessible numeric tables. Compare against the median of the preceding comparable sprints, excluding the selected sprint. Show sample size; suppress cycle-time P85 at n < 10 with an explanation.

Show duration, capacity notes, workflow mapping changes, estimate coverage and history coverage. Do not compare raw points across teams. Never fill missing sprints with zero or silently mix count and point ratios. Aggregate throughput across sprints by completion occurrence with explicit cohort rules, not repeated sprint membership.

### Retrospective

Goal assessment, human review note, optional structured causes, and improvement actions. Actions include title, source suggestion or issue IDs, owner, due date, Open/In progress/Done status, completion date and follow-up evidence. Keep overdue derived from due date/status. Show previous actions separately from actions created for this sprint. Link future follow-up to the originating sprint.

### Common issue table and drawer

Default columns: issue key, summary, type, assignee at close, scope, status at close, points. Scope/status labels include their time basis. Original estimates remain start estimates in the default point column; added estimates use first in-sprint entry, with later values in the drawer. Removed rows use values at final removal, not an invented closing membership.

Quick filters: All work, Original plan, Added, Removed, Unfinished, Reopened, Blocked, Unestimated. Support search over key/summary, assignee, epic, application, type and closing status. Multiple scopes may intersect; show active filter chips and Clear all. Suggested default page size: 25, with server pagination; page reset on filter changes. Optional grouping by assignee, epic, application or closing state. Sorting is stable with issue ID tie-breaker.

Drawer: closing snapshot; original/entry and closing estimate; membership timeline; status timeline; recorded blocker intervals; manual reason; relevant evidence links. Identity means assignee at the given timestamp, not credit for every contribution. Keep current Jira values in a clearly separated section only if fetched and authorized. Provide **Group by developer at close** in the past table as well, preserving the familiar grouping option with an explicit historical basis.

## 5. Role-specific analysis views

### Shared interaction contract

The previous design only filtered issue rows and reordered the same three suggestions. This revision supersedes that behavior. Use **one page-level View as** selector in Past sprint analysis. It governs the Overview composition, leading role measures, initial issue focus, suggestion priorities and fixed discussion prompts. Keep the chosen analysis tab on role changes; the current role description remains visible above every tab. Flow & Quality, Trends and Retrospective are shared evidence workspaces, with the same calculations accessible to all roles. Do not manufacture different answers to the same metric.

Role choice is a reversible preference, not a permission boundary. Shared goal and five sprint totals always refer to the entire authorized sprint population. Every personal/subset card names its population. Default issue focus is visible and independently editable: All issues, Selected developer, Stories or Unfinished at close. Changing focus does not change the selected role or team totals. Metric and suggestion drill-downs replace incompatible table filters so the full advertised evidence population is visible; subsequent user filters explicitly narrow it. Clear filters retains the role. Pagination resets when the population changes. CSV uses exactly the visible table filters, with sprint, snapshot, role, population and time basis in its metadata.

Preserve the selected closed sprint, report revision and role/filter state. Production URLs restore role, tab, developer ID and safe filters. Never encode human notes in a URL. The review prototype persists role in `?view=` and tab in the hash; other filter/developer restoration is production work. Role changes must preserve unsaved assessment/action drafts.

### What changes for each role

| View and decision | Four leading measures | Distinct evidence sections | Initial issue focus / discussion |
| --- | --- | --- | --- |
| Team: what did we deliver and what remains? | Added-work completion; completed cycle median; repeated carryover; goal-linked unfinished | Developer contribution context; scope movement and recorded reasons; work mix; shared original-plan outcome | All issues; agree completion follow-up and team actions |
| Developer: what work was assigned to me and what needs follow-up? | Assigned closing scope; assigned completed; assigned unfinished; full-issue cycle median of assigned completions | Selected developer contribution row; unfinished ticket status/age; assignment timeline, reviews/support where explicitly recorded | Selected developer at close; queue/handoff and next steps for affected tickets. Select another authorized developer explicitly; real account identity is canonical, not a hard-coded name |
| PO / BA: what intended scope was delivered and accepted? | Goal-linked completed; explicitly accepted stories; Done stories awaiting acceptance; changed issues missing reasons | Sprint-scoped feature/epic delivery; original/added/removed split; scope reasons; human goal assessment and review/demo links; remaining goal-linked work | Stories initially; goal-linked evidence may include any configured issue type. Scope-change rationale, acceptance and remaining business scope |
| Scrum Master: where did flow slow and what action should follow? | Completed cycle median; closing review queue; repeated carryover; currently open improvement actions | Unfinished age and stage; repeated closes; stage times, blocker intervals and WIP when available; action owners/due dates and previous action follow-up | Unfinished closing scope; review queue, recurrence and accountable follow-up |
| Engineering Manager: how consistent is delivery and where is support needed? | Original-plan completion; throughput versus preceding median; gross scope movement; completed cycle P85 | Comparable multi-sprint table/series; work mix and quality context; contribution by closing assignment; capacity notes and explicit dependencies | All issues; inspect variation, constraints and support needs using team context |

### Developer contribution: useful detail with explicit attribution

The default table is **Developer contribution · assignment context**, ordered by developer name rather than a score. Columns: canonical developer identity, closing-scope issue count, completed issues and baseline/entry points, unfinished, removed (at removal identity), share of team completed count, and Story/Bug/Task split of retained work. Each numeric issue cohort opens its exact issue list. Include Unassigned and unknown/deactivated identities; shared display names must not merge distinct people. Optional columns: original versus added completion, repeated carryover, reopened assigned work and missing estimates.

Closing assignment is one ownership snapshot, not a full contribution ledger. Label assignment basis on the table and export. Add optional **Assignee at completion** and **Assigned at any time during sprint** lenses only after assignment events exist. The latter is many-to-many: an issue may appear for several people, so totals must not be presented as additive. Preserve before/after assignment timestamps and unknown intervals. Do not silently assign all work to the final owner or divide points between people without an agreed recorded allocation.

Additional contribution evidence, when available: named review participation, pairing records, test execution, operational support, mentoring/documentation and recorded handoffs. Store explicit contributor, activity kind, source link and timestamp; human-entered records require an author and audit history. Show these as contextual activity, with duplicate sources deduplicated, rather than a weighted productivity score. Comments, commits, ticket counts, point shares and cycle times alone cannot establish effort or performance. A ticket's cycle time includes other contributors and waits. No individual targets, rankings, performance grade or inferred utilization are part of this feature.

### PO / BA: distinguish completion, acceptance and outcomes

Goal linkage is explicit metadata (configured field/link or human association), with source and timestamp. Never infer it from an epic title or description. Feature delivery counts refer to this sprint's scope, not overall epic completion. Freeze links at the report revision and label later edits. Show all added/removed issue types in scope evidence even when the issue table defaults to Stories.

Acceptance is separately recorded as Accepted / Pending review / Rejected / Not ready / Not recorded, with actor, time and evidence. Define applicable types per board. Done remains the workflow measure; Accepted remains a business review fact. Show acceptance coverage alongside the eligible denominator. The sample's accepted story ratio uses retained stories, including unfinished stories, and is labelled accordingly. A production alternate ratio of accepted Done stories must name that different denominator.

The human goal assessment remains Not assessed until saved. Support achieved/partial/not achieved, note, demo/review evidence, author and correction history. Release status and measured business outcomes require explicit deployment and product evidence. Neither all goal-linked tickets Done nor 100% points proves the sprint goal or business outcome. Requirement changes need versioned acceptance-criteria/requirement records, with a visible unavailable state until supported.

### Scrum Master: distinguish recorded constraints from explanations

Show completed flow and unfinished age together, with elapsed units, sample size and coverage. A queue at close is a snapshot, not proof that review caused delay. Daily WIP and per-stage occupancy require interval history. A configured WIP limit requires its effective dates; report days above that limit only for known days. Explicit blocked intervals may overlap other stages and must be unioned per issue. Follow blocker dependencies to named owners where access allows, with open/missing/unavailable states.

Separate sprint-frozen facts from **Current action status**. Actions support owner, due date, state, completed date and follow-up evidence. Overdue means an unfinished action with a due date before the observation date in the configured timezone. The action-due cohort is separate from all open actions; calculate follow-through on actions due by the selected review date, not all future actions. Historical review snapshots can be retained without falsifying current status.

### Engineering Manager: predictability with context

Predictability is a group of descriptive measures, not one composite score: original-plan completion, throughput trend, cycle-time distribution, scope movement and variation across comparable sprints. Show the previous 5–7 eligible sprints for a 6–8 sprint display. Exclude the selected sprint from its baseline; show sample count, exclusions and missing history. Compare the same board/team, definition of Done mapping, issue inclusion and duration; show workflow/calendar/estimate changes. An exploratory override must label the mixed cohort rather than imply comparability.

Show capacity as recorded team availability (for example available team-days after planned leave), with source and effective period. Separate planned and actual records. Missing capacity must not become zero or an inferred per-developer utilization. Work categories such as feature, maintenance, defect, operational support and technical debt require an explicit mapping or tag; unmapped records remain Unknown. A Bug issue type is not proof of a production escape. Linked escaped defects need a defined release cohort and post-release observation window. Support decisions may use these facts and human context; automatic causal narratives or forecasts are excluded.

## 6. Historical metric contract

### Time and population

- `t0`: verified actual sprint activation when available; otherwise configured start with explicit fallback provenance.
- `t1`: actual completion; use `[t0, t1]` boundary semantics consistently. Resolve same-timestamp events by stable source sequence when available; ambiguity is surfaced, not guessed.
- Store UTC instants; display board timezone, default Asia/Kolkata for this deployment until configured otherwise. Late-addition rules use the board working calendar.
- Include standard issue types in headline counts; subtasks remain available in detail and are excluded to prevent double counting. Freeze issue-type inclusion mapping/version.
- Baseline `O`: issues in the sprint at activation. Track already-Done members separately and exclude them from planned new delivery ratios. Make the count of exclusions visible.
- `A`: issues absent from O that enter during the sprint. Distinct issue membership counts differ from repeated add/remove event counts.
- `R`: issues in the union O∪A but absent at close after removal. Returning issues retained at close are not R, but still contribute membership-change events.
- `D`: issues in closing scope that meet the configured Done mapping at t1. Done status is an operational proxy; Definition of Done compliance and stakeholder acceptance need separate evidence.
- `U`: closing members not in D. Cancellation mapping is explicit, not silently Done.
- Partition O and A separately into done, unfinished and removed. This avoids subtracting removed added work from original commitment.
- If baseline/closing membership cannot be reconstructed completely, suppress exact ratios or label covered-population values with numerator/denominator coverage. Never mix current fallback values into a supposedly historical total.

### Metric dictionary

| Metric | Definition | Required evidence / edge cases |
| --- | --- | --- |
| Planned issues | `count(O_eligible)` | Baseline and already-Done exclusion |
| Original-plan completion | `count(O_eligible ∩ D) / count(O_eligible)` | Zero denominator = N/A |
| Planned points | Sum known estimates at t0 over O_eligible | Null stays null; display estimated/eligible counts |
| Planned-point completion | Sum start estimates for completed original / sum start estimates for eligible original | Same weights in numerator and denominator; zero points = N/A; partial estimate coverage labelled |
| Completed issues | `count(D_eligible)` | Retained at close; original + added; exclude already-Done entries |
| Delivered baseline points | Sum fixed start/first-entry estimates over D_eligible | Name the basis; closing points are a distinct optional metric |
| Unfinished at close | `count(U)` split into original/added | Does not prove the item entered the next sprint |
| Scope additions | `count(A)` | Distinct added issues, including subsequently removed ones |
| Scope removals | `count(R)` split original/added | Final removals; show event churn separately for remove/re-add |
| Membership churn | Number of add/remove events after activation / original eligible issue count | Can exceed 100%; not the same as unique changed issues |
| Estimate movement | Signed changes to estimates during the sprint | Keep separate from membership changes; preserve null↔number events |
| Carry-in | Current original issues unfinished at an earlier relevant sprint close | Requires historical sequence; multiple membership alone insufficient |
| Repeated carryover | Same issue unfinished in closing scope at >=2 consecutive relevant sprint closes | Compare same board lineage; skipped membership breaks sequence; parallel sprints need explicit handling |
| Cycle time | Start of first configured active state to terminal Done transition leading into closing Done interval | Completed cohort only; includes elapsed waits/reopens; show start before sprint |
| Closing age | t1 minus first active-state entry for unfinished issues | Not-started issues shown separately; never age through today |
| Stage time | Sum intervals in a configured stage, clipped to sprint window | Gaps/unknown history invalidate exact totals |
| Blocked duration | Union of explicit blocked intervals clipped to sprint | Overlap merged; open interval ends at t1; flag and status mapping documented |
| Reopened issues | Unique issues with Done→non-Done transitions during sprint while members | Include currently Done-again issues; event count separate |
| Unestimated | Missing baseline/entry estimate among eligible issues | Zero is an estimate, not missing |
| Work mix | Counts by mapped type; optional point share with coverage | Issue type is not automatically business-value category |
| Escaped defects | Linked defects attributable to delivered work, discovered in stated post-close window | Later observed evidence; window/version shown; no AI attribution |

Percentiles use a documented algorithm (nearest-rank for v2), sample size and units. Daily charts replay events from a known baseline; missing event history is not a zero-duration interval. Freeze mapping versions and calendar versions with each calculation.

### Additional metric contracts for the role views

All ratios return N/A when their denominator is zero. Coverage includes eligible count, measured count and reason for exclusions; a known subtotal is never an exact whole-team result. Use issue counts first. Optional point lenses retain start/entry weights; missing estimates are not zero. Do not mix start, entry and current estimates in one ratio.

| Measure | Exact contract and interpretation | Display / evidence |
| --- | --- | --- |
| Added-work completion | `count(A ∩ D_eligible) / count(A_eligible)`; added-then-removed work remains in denominator | Sample 3/5 = 60%; original completion remains 18/24 = 75% |
| Gross scope movement | `(count(A) + count(R)) / count(O_eligible)`; sums additions and final removals | Sample 7/24 = 29.2%. An added-then-removed issue contributes to both A and R. This is movement volume, not a unique affected-issue percentage |
| Unique changed-issue ratio | `count(A ∪ R) / count(O_eligible)` | Sample 7/24 = 29.2%; may differ from gross movement when sets overlap. Use this definition for SV-07 |
| Net scope growth | `(count(A) − count(R)) / count(O_eligible)` | Sample 3/24 = 12.5%; never shown alone because opposite changes cancel |
| Addition/removal rate | Show `count(A)/count(O_eligible)` and `count(R)/count(O_eligible)` independently | Sample 20.8% added / 8.3% removed |
| Membership event churn | Count every post-start membership add/remove event, divided by original eligible count | Separate from gross/unique movement. Remove/re-add loops contribute repeatedly; preserve ordered events |
| Scope-reason coverage | Changed issues with a nonempty recorded reason / all distinct changed issues | Missing reason is a data gap, not evidence of an unjustified change. Event-level reasons are needed for repeat moves |
| Closing reconciliation | `count(O ∪ A) = count(D) + count(U) + count(R)` for the complete mutually exclusive closing/removal partition | 29 = 21 + 6 + 2; closing scope = 24 + 5 − 2 = 27. Delivery-eligible counts may differ if already-Done exclusions exist |
| Goal-linked delivery | Completed explicitly linked eligible issues / explicitly linked eligible sprint scope | Show Done, unfinished, removed separately. Not a goal achievement score |
| Acceptance coverage and completion | Recorded acceptance state / applicable retained stories; Accepted / applicable retained stories as a separate ratio | Show missing states. Do not relabel a Done count as Accepted |
| Assigned completion share | Completed issues with closing assignee X / all team completed issues | Disjoint closing-assignee lens reconciles to 100%, including Unassigned/unknown. Share is ticket attribution, not effort or value |
| Assigned closing completion | Completed closing assignments / all retained closing assignments for X | Optional descriptive measure; do not call it individual commitment reliability. Use activation assignment events for an explicitly separate initial-assignment cohort |
| Assigned cycle median | Median full-lifecycle cycle duration for completed issues assigned to X at the selected attribution timestamp | Elapsed issue duration, not individual labor. Display n; suppress P85 for n < 10 |
| Cycle P85 | Sort valid cycle durations ascending, select rank `ceil(0.85 × n)` (one-based) | Sample n=21, rank18, 6 days. n<10 => insufficient sample. Zero valid durations => unavailable |
| Throughput baseline | Median completed eligible issue count over preceding comparable sprints, excluding selected | Sample previous counts 20/23/19/22/20: median20, observed range19–23. Selected21 |
| Plan-completion baseline | Median of each prior sprint's original-plan completion ratio, not pooled numerator/denominator | Sample previous-five median78.3%; selected75%, difference −3.3 percentage points |
| Delivery variation | Observed min/max and optionally median absolute deviation over preceding comparable throughput | Sample median20, absolute deviations0/3/1/2/0, MAD1 issue. A small n is descriptive; range is not a prediction interval |
| Action follow-through | Actions completed by observation date / actions due on or before observation date | State/complete timestamp and due-date history required; current status is separately labelled |
| Work-category share | Eligible retained work in an explicitly mapped category / all eligible retained work, including Unknown | Counts first; original/added and completed/unfinished splits optional; do not infer debt/support from prose |

Cycle time spans first active entry to the final Done interval leading to closing Done, even when work starts before the sprint. Per-stage **time within sprint** clips to [t0,t1]; per-stage **full cycle time** uses the full lifecycle and must have a different label. The preview's completed stage samples happen to fit within the sprint. Reopened intervals contribute to the full cycle; unfinished items have closing age and no completed cycle value. Never subtract independent stage medians to derive waiting time, and never sum them into a median total.

Priority order: baseline/closing reconciliation and scope facts first; goal/acceptance/assignment context next; event-based cycle/age/flow and comparable trends after history ingestion. Daily WIP, work-category mapping and capacity context follow verified source availability. No role should appear complete while its defining section is silently absent.

## 7. Deterministic suggestions catalogue

Initial defaults below are proposals for team configuration, not universal benchmarks. Rules return structured facts and issue IDs, never free-form inference. Sort by configured category priority, affected count descending, rule ID. Cap Overview at three; Suggestions shows all.

| ID | Trigger / required evidence | Fixed suggested next step |
| --- | --- | --- |
| SV-01 Review queue | >=1 unfinished member mapped to Review at t1; closing status complete | Review the queue together and record any shared constraint. |
| SV-02 Late addition | >=1 first-added issue during final 2 configured working days; membership events complete | Check the recorded reason for the late change and whether future planning should account for it. |
| SV-03 Repeated carryover | >=1 issue unfinished at >=2 consecutive relevant sprint closes | Discuss whether the item needs slicing, clarification or dependency follow-up. |
| SV-04 Explicit blocker | >=1 issue blocked for >=2 working days (or separately configured elapsed hours); complete interval evidence | Review the recorded blocker and agree an owner for follow-up. |
| SV-05 Reopened work | >=1 Done→non-Done issue during sprint | Inspect the transition and record what additional work was needed. |
| SV-06 Missing estimates | >=1 eligible issue without baseline/entry estimate | Confirm whether estimation is expected for this work type. |
| SV-07 Frequent scope movement | Distinct changed-issue ratio above configured threshold; complete membership | Review changes and their recorded reasons. No automatic negative judgment. |
| SV-08 Aging unfinished work | >=1 active unfinished issue older than configured elapsed threshold at t1 | Review remaining work and next steps. |
| SV-09 Overdue action | Due date before observation date and action not Done | Confirm ownership and update the next step or due date. |
| SV-10 Delivery variation | Selected throughput outside configured comparison range with >=5 comparable previous sprints | Review capacity and scope context before changing forecasts. |

For SV-09, explicitly label **Current action status**, since this observation is not frozen at sprint close. Trend deviations are descriptive, not diagnoses or predictions.

Rule execution states: matched, not matched, unavailable, disabled. Persist reason codes for missing fields/history/calendar/comparison population. Track coverage per rule, including issues checked/excluded. Suppress exact headline observations on incomplete required coverage in Release A.

Observation payload: `rule_id`, `rule_version`, `config_version`, `snapshot_id`, `input_revision_ids`, `status`, `category`, `facts`, `evidence_issue_ids`, `coverage`, `threshold`, `time_basis`, `template_key`, `created_at`.

Stable identity: scoped sprint + rule version + sorted evidence membership + relevant facts. Save dispositions separately with author and revision. If evidence changes, label **Updated evidence** and preserve the previous disposition record. Config changes trigger an explicit recomputation/version change.

## 8. Data and backend changes

### Proposed additions

1. `SprintEventRevision`/normalized event rows tied to snapshot component revision: source issue ID, history ID/item ordinal, UTC time, field ID, old/new values, provenance, coverage range. Deduplicate with source IDs; index revision+issue+time and revision+field+time.
2. `SprintBoundaryIssue` projections: baseline/entry/closing membership, status, estimates and identity, with per-field provenance and exclusion reason. Include removed issues from authorized metric memberships, not only the sprint issue endpoint.
3. `SprintAnalysisRevision`: metric values, membership references, availability, samples, time bases and algorithm/config versions; atomic publication from immutable inputs.
4. `SprintObservation` and disposition records: rule result/evidence and separate human workflow state.
5. `SprintReviewNote` and `SprintReviewAction`: mutable human records with optimistic concurrency, audit metadata, restoreable archive and validation.
6. `SprintAnalysisConfig`: board mappings, calendar, type inclusion, rule thresholds and effective/version dates.

Fit these into existing source/user/access scope and revision models. Do not store credentials in any new payload. Reuse Jira identity resolution; same display name does not prove the same person.

Initial review notes/actions are private to the report owner because current snapshots are user-scoped. A shared team retrospective requires an explicit board-level collaboration permission model before launch; never achieve sharing by removing the scope predicate. The prototype's local notes do not imply shared server persistence.

### Proposed route contract (names to finalize within existing registration conventions)

- `GET /automation/sprint-viewer/views/{view_id}/analysis`: summary, counts and component availability for a granted view.
- `GET .../issues`: allowlisted filters, sort, pagination, optional observation ID resolved server-side.
- `GET .../issues/{issue_id}/timeline`: authorized, paginated historical evidence.
- `GET .../suggestions`: category/status filters, rule coverage and evidence counts.
- `GET .../trends`: bounded comparable sprint set; independently authorized source snapshots.
- `POST .../assessment` and `POST .../actions`: CSRF-protected, validated human writes; idempotency key and expected revision.
- `PATCH .../actions/{action_id}` and `POST .../suggestions/{id}/disposition`: owner/board permission checks, conflict response and audit history.
- Export uses the same granted snapshot/revision/filter definitions, with readiness checks and spreadsheet formula-injection protection.

Reuse `json_ok`, `json_error`, safe errors, request IDs, existing grant ownership and expiry checks. Refresh analysis means a new candidate generation with explicit user action; refreshing the sprint catalog alone does not refresh report data. Preserve prior complete generation until replacement is publishable.

### Proposed code organization

```text
app/features/automation/sprint_viewer/
  calculations.py                 compatibility/public aggregate entry
  analysis/boundaries.py           event replay and historical populations
  analysis/metrics.py              pure metric functions
  analysis/rules.py                pure rule predicates and facts
  analysis/catalog.py              rule metadata and message templates
  analysis/coverage.py             availability and provenance
  analysis/trends.py               comparable cohorts
  review_service.py               validated human edits
  models.py / repository.py / jobs.py / routes.py
app/static/js/sprint_viewer/
  state.js / api.js / overview.js / issues.js
  suggestions.js / flow.js / trends.js / retrospective.js
app/static/css/sprint_viewer.css
app/templates/automation/sprint_viewer.html
```

Keep the existing JS entry path as a compatibility loader if splitting modules. Share selectors, pagination, stale-response handling and export state; avoid a second competing global state object.

## 9. UX system, responsiveness and accessibility

Visual tokens: canvas #f5f7fa, white surface, text #172b4d, muted #59677e, divider #e1e6ee, accent #465bd8, done #177a68, unfinished #986313. System font stack avoids font-network dependency. Headings 28/20/16px; body 14px, utility minimum 12px. Spacing 4/8/12/16/24/32; modest 8–12px corner radii. Prefer flat bands, rows and panels over nested cards. No decorative imagery required.

Desktop >=1100px: five metrics across, 2:1 overview, full-width table. Tablet 720–1099px: wrap metrics and stack overview panels. Mobile <720px: stack header and sections, horizontally scroll tab strip and table within labelled regions; drawer becomes full-screen. Keep issue key and summary readable; optional columns collapse behind details. Controls target at least 44px on touch.

Use semantic headings, real buttons, labelled selects, table headers, visible focus and non-colour status text. Navigation tabs support arrows/Home/End with focus and selected state; drawer/dialog trap focus and restore it to the opener. Escape closes overlays. Search result counts use polite live announcements. Charts have text equivalents. Respect reduced motion; no auto-advancing carousel or animated numbers. Validate contrast, 200% zoom, keyboard-only navigation and small-screen overflow.

Selection/filter state belongs in the URL where safe (IDs and enum values, no notes or credentials). Back/forward restores it. Role preset does not erase a drafted note. Warn about unsaved human edits only when navigation would discard them. Avoid full-screen loading overlays after the shell exists.

## 10. State and error matrix

| State | UI response |
| --- | --- |
| No sprint selected | Compact selector and explanation of closed-sprint scope |
| Import queued | Show queue/progress in place; keep selectors usable |
| Core ready, analysis pending | Render issues; skeleton metrics with “Calculating historical analysis” |
| Ready empty sprint | Zero counts, ratio N/A, meaningful empty table; valid cache hit |
| History unavailable | Keep authorized core values marked current; suppress historical-only charts and rules |
| Partially estimated | Counts usable; points show coverage and incomplete label |
| Enrichment failed | Local retry; do not discard usable core snapshot |
| Access expired/denied | Stop displaying/exporting affected data and offer normal reauthorization flow |
| Snapshot refreshed | Explain new generation; retain manual review records and flag changed evidence |
| Conflicting manual edit | Preserve draft; show updated record and require explicit reconciliation |
| No rule matches | Neutral empty state plus evaluated-rule count |
| Rule prerequisites missing | Dedicated unavailable count and reason; not “no problems” |

## 11. Performance and operations

Provisional acceptance budgets, to validate on the production host and representative Jira data: cached analysis API p95 <=500ms after a valid grant; cached first usable view <=1.5s; local filter feedback <=150ms; new frontend assets <=100KB gzip excluding existing shared portal assets. Cold Jira authorization/import has separate measured budgets and is not included in these claims.

Paginate 25–50 issues and lazy-load timelines, trends and comments. Persist event/analysis components once per immutable revision; cache rule results against explicit dependencies. Avoid per-row synchronous Jira calls in read endpoints. Preserve reserved core/access request capacity and fence checks. Bound trend imports (initially 8 sprints) and let users cancel enrichment. Avoid concurrent long writes on SQLite; batch event writes in short transactions. Record query timings, history coverage, deduplication counts, rule duration, queue latency and asset size without raw private content.

## 12. Implementation work packages and acceptance

| Phase | Work | Acceptance gate |
| --- | --- | --- |
| 0 — Contract | Verify Jira fields, history capability, Done/Review mappings, type inclusion, calendar, existing routes and representative fixtures | Signed-off metric examples for zero, missing, remove/re-add, already Done, reassignment and late close cases |
| 1 — Evidence | Add event adapter, coverage/provenance, removed-issue discovery and boundary projections | Replay reconstructs known start/close states; unsupported history is unavailable; permission isolation preserved |
| 2 — Calculations | Pure population, metric and initial rule functions; versioned publication | Metric totals reconcile to exact evidence sets; no current-point contamination; overlap fixtures pass |
| 3 — UI foundation | Closed-sprint shell, summaries, historical issue table/developer grouping/drawer, responsive states and export | All aggregates drill down correctly; keyboard/mobile checks; old route compatibility passes |
| 3a — Role analysis | Single role selector; distinct role sections; contribution cohorts; feature delivery; manual goal/acceptance/scope metadata; unavailable states | Each role changes meaningful content; identical shared totals; exact evidence population after filter replacement; explicit assignment basis; no hidden personal denominator |
| 4 — Suggestions and review | Observation list, rule explanation, actions, assessments and dispositions | Evidence counts match; writes validated/audited; refresh preserves decisions; no AI dependency |
| 5 — Flow/trends | History durations, burnup/WIP, comparable sprint cohorts and coverage | Known-event fixtures match durations; missing data not zero; samples and mappings visible |
| 6 — Pilot | Feature flag for selected users, side-by-side reconciliation, feedback and performance measurements | Representatives of all roles complete the four main tasks; agreed budgets/checks pass |
| 7 — Rollout | Enable gradually, operations guide, migration/rollback runbook | No permission regressions; worker stable; rollback tested |

Indicative effort only: approximately 30–49 engineering days for the historical scope, including distinct role composition, attribution/acceptance metadata and reconciliation checks. Active-catalog/freshness work is excluded. Re-estimate after validating the supplied field catalogue and Jira-history capabilities. External review/deployment integrations, complete contributor attribution and unsupported history adapters require separate estimates. This is an unvalidated planning estimate, not a delivery commitment.

## 13. Required verification

Before behavioral production changes, follow the repository rule to add/update relevant tests. Keep prototype checks separate from production validation.

- Unit: start/close cutoffs, equal timestamps, null/zero estimates, changed estimates, points coverage, already-Done entries, added then removed, removed then re-added, original versus added removal, reopened and Done again, status configuration, reassignment aliases, overlapping blocker intervals, missing history, percentile/sample rules, calendar holidays and daylight-saving boundaries.
- Integration: core/history/metric discovery union; pagination limits; immutable inputs; idempotent imports/actions; worker stale fence; partial publication; grant expiry; revoked access; another user's action/snapshot; concurrent human edits; migration from current SQLite schema; rollback preserving notes.
- Browser: all tabs/presets/search/filters/reset; evidence counts; drawer focus; assessment/action validation; unavailable states; narrow screens; 200% zoom; export consistency; stale sprint switches; errors while tickets remain usable.
- Performance: representative 50/250/1000-issue fixtures; cached versus cold reads; bounded trend import; no N+1 history requests on reads; SQLite lock time.
- Product: a developer finds a delayed issue; PO traces a scope change; scrum master creates an evidence-linked action; manager compares only compatible sprints. Record time, confusion and incorrect interpretations.

## 14. Decisions and remaining validation

Defaults chosen for implementation: closed-sprint analysis only, direct Overview entry, historical developer grouping, counts first for historical metrics, optional points, standard issues only for headlines, no AI, current stack, private review records initially, actual-close historical boundary, explicit mapping versions, six-sprint trend window and deterministic suggestions. The preview represents one sample board with one closed sample sprint; it deliberately does not connect to Jira.

Before production work, establish: deployed Jira/DC and ScriptRunner versions; complete-history endpoints; permission semantics; baseline activation field; workflow/blocked mappings; expected sprint size; calendar; acceptance/goal-link fields; whether review records must be team-shared. These are implementation discovery items, not blockers to reviewing the proposed interface.

Reference principles consulted in this conversation: [Scrum Guide](https://scrumguides.org/scrum-guide.html) for Sprint Goal/review/retrospective purpose; [Atlassian Sprint Report](https://support.atlassian.com/jira-software-cloud/docs/view-and-understand-the-sprint-report/) for reporting semantics (Cloud reference, not evidence of deployed DC API support); [DORA metrics](https://dora.dev/guides/dora-metrics/) for keeping delivery-system performance separate from ticket activity. The specific rules and thresholds above are this proposal, not mandated Scrum practices.

## 15. Role revision delivery and review gates

### Data and API additions

Extend existing scoped components rather than adding one API per role. Compute a shared analysis revision containing metric IDs, raw numerators/denominators, units, population keys, availability, coverage, time basis and mapping versions. Role layout configuration references these IDs. A role change should reuse cached authorized facts; it should not start another Jira import or create a competing metric definition. Fetch optional trend/detail data lazily and retain core tickets when it fails.

Proposed schema additions, finalized after field discovery:

- Normalized assignment events: immutable issue ID, timestamp, previous/next canonical principal, source sequence and history completeness. Preserve unknown principals and ambiguity.
- Goal associations, acceptance records and scope reasons: scoped sprint/issue, source kind (mapped Jira field or human record), source/evidence reference, state or reason, effective timestamp, author, revision and audit timestamps. Distinguish an at-close record from an assessment entered after close; preserve both effective and recorded times.
- Optional contributor records: issue, contributor identity, activity kind, event timestamp, source link and deduplication key. Do not synthesize them from mentions/comment volume.
- Team context: availability units and effective period, source, planned/actual qualifier, recorded dependencies and responsible team/person. Missing inputs are explicit.
- Evidence cohorts: authorized issue IDs associated with a stable metric ID/report revision. Server queries and exports must apply the same membership predicate; do not trust client-provided IDs to bypass authorization.

Use existing read grants for all role views. Human writes follow current owner/team scope, input validation, optimistic concurrency and audit patterns. Prototype browser storage is never the production persistence contract. Personal role preference must not grant access to another person's records. Goal/acceptance/reason edits trigger only dependent revisions and retain old evidence rather than overwriting historical facts silently.

### Production acceptance scenarios

1. Switching each of the five roles produces the distinct heading, four leading measures, required evidence sections and visible default focus in section 5. Shared sprint totals stay identical. Missing defining evidence displays Unavailable with a reason.
2. Start in PO / BA, inspect a team review-queue suggestion containing Tasks/Bugs, and receive the entire evidence population. The role stays PO / BA; the overridden issue focus is visible. Clear filters retains the role; CSV contains the filtered cohort and provenance.
3. An original issue is removed/re-added, and an added issue is later removed: final closing scope reconciles; gross movement, unique changed-issue ratio, net growth and event churn differ as defined. Estimate changes do not silently change original points.
4. An issue is reassigned between two developers and paired on: closing-assignee totals count it once; any-time assignment may count it for both and is labelled non-additive; explicit contributor events remain separate. Unknown/Unassigned identities remain visible.
5. A sprint has no completed issues, nine completed cycles, missing start transitions, reopened work and an item started before the sprint: medians/P85/age behave according to the cohort/coverage rules. Age stops at close; days are elapsed time.
6. A story is Done but acceptance is missing or rejected: completion is preserved; acceptance remains missing/rejected. A goal assessment stays Not assessed until a human saves it. Later evidence is labelled with its recording time.
7. Trend selection excludes the selected sprint from its baseline; missing or incomparable history is never zero-filled. Ratios use declared denominators; percentage-point change is not labelled percentage change. Small samples do not produce a confident forecast.
8. Manual goal assessment and action edits retain authors, timestamps and revisions; current action state updates role measures without rewriting closing facts. An edit conflict preserves the user's draft.
9. Only closed sprints are selectable/importable. Default and legacy preview links open historical Overview; no active workspace exists. Switching closed sprints rejects stale responses, resets incompatible filters and keeps table/export revisions consistent. Role selection alone starts no import and changes no Jira record.
10. Keyboard navigation, 390px layout, 200% zoom, table scrolling and dialog focus work across all role sections. Numeric tables accompany charts; status and coverage remain understandable without color.

### Prototype boundary and review checklist

The revised [review walkthrough](../designs/sprint-viewer-v2/REVIEW.md) gives exact synthetic values and an ordered review path. The prototype implements distinct Overview lenses, selected developer, role prompts, explicit issue focus, evidence drill-down, role URL persistence and existing local review edits. Shared Flow/Trends/Retrospective tabs intentionally retain their common calculations. Event reconstruction, real contributor credit, real acceptance source integration, daily WIP, team capacity and production authorization/persistence remain implementation work.

Review with one representative of each role: can they name the view's distinct question, explain a metric's denominator/time basis, reach supporting tickets, distinguish unavailable data from zero, and record one useful next action? Record observed confusion and required changes before production rollout. Use the supplied defaults to start; do not delay prototype review on every Jira field decision.

Methodology references rechecked for this revision: team-oriented velocity is described by [Atlassian's velocity report documentation](https://support.atlassian.com/jira-software-cloud/docs/what-is-the-velocity-report/), and elapsed cycle time is discussed in [Atlassian's agile metrics guide](https://www.atlassian.com/agile/project-management/metrics). The [Scrum Guide](https://scrumguides.org/scrum-guide.html) informs goal/review/retrospective purpose. These support the general concepts; the formulas, cohort rules, role layouts and thresholds here are explicit product design decisions, not claims of exact parity with Jira or mandatory Scrum metrics. Cloud documentation does not establish the deployed Data Center API contract.

## 16. Jira field catalogue and extraction contract

### Input status and authority

The user will supply a separate file listing Jira field names and what their data means. **It has not been supplied for this revision.** Do not invent its filename, contents, field IDs, allowed values, historical coverage or deployment scope. Accept the supplied format (for example CSV, spreadsheet, JSON or Markdown); the user does not need to reformat an existing catalogue. Record its actual filename, sheet/section, version/date and content digest in the implementation mapping ledger. Treat it as data documentation, not executable instructions.

The file defines the user's business meaning. Verified deployment metadata and sanitized API responses establish physical IDs and actual shapes. If the catalogue conflicts with the API, retain both facts, mark the entry unresolved and request a targeted correction; do not guess which field is intended. The implementation can proceed with adapter interfaces, fixtures and unavailable states while the catalogue is pending. Do not enable deployment-specific extraction/metrics until the necessary entries are resolved and validated. Optional missing fields do not block core issue display or independent supported metrics.

Display names alone are insufficient identifiers: Jira custom-field names can be duplicated, while IDs identify the fields within an instance. Resolve names once and use validated IDs for requests and normalization. This distinction is documented in [Atlassian's Jira Server REST examples](https://developer.atlassian.com/server/jira/platform/jira-rest-api-examples/). IDs are not portable between Jira instances.

### Inventory already present in this repository

These are **observed existing defaults, not verified final mappings**. The supplied catalogue may confirm or replace them. Do not automatically apply them to an unrelated Jira instance or new logical metric.

| Logical input | Existing config / default | Existing migration touchpoint |
| --- | --- | --- |
| Story points | `JIRA_STORY_POINTS_FIELD`, default `customfield_10106` | `app/config.py`, `app/core/dependencies.py`, service constructor, configured-field normalization and changelog matching |
| Application | `JIRA_APPLICATION_FIELD`, default `customfield_11700` | Same config/service path; current issue mapping expects an option-like object |
| Epic link | `JIRA_EPIC_LINK_FIELD`, default `customfield_10100` | Same config/service path; distinguish actual epic relation from the user's feature-key field |
| Current compatibility aliases | `normalize_configured_fields` copies values into the three fixed legacy keys above | Preserve a legacy output adapter while new analysis uses logical names; do not mutate an immutable raw response or let aliases overwrite real source fields |
| Point changelog matching | Existing reconstruction accepts the name `story points` or fixed `customfield_10106` | Make new historical matching registry-driven; changing the request field alone does not fix history extraction |
| History request fields | `app/features/automation/sprint_viewer/jobs.py` builds an explicit list using the service's three configured IDs | Extend through one registry-based field selection function for core, history and removed-issue fetches |
| Standard fields and identity | `summary`, `issuetype`, `status`, `assignee`, `parent`, `project`, `updated`; `app/integrations/jira/identity.py` | Keep standard field paths and reuse canonical identity resolution; do not create custom-field mappings unnecessarily |

Search all downstream reads in the service, jobs, metric calculations, exports and tests before replacing legacy aliases. Keep existing config variables backward-compatible as an explicit legacy mapping input. A validated board/project-specific registry entry takes precedence over an instance entry, which takes precedence over legacy config only for those three existing concepts. Record which source won. Never merge incompatible types, silently use an unrelated similarly named field, or default a new optional concept to a legacy ID.

### Catalogue resolution workflow

1. Inventory the user's file, including exact display name, meaning, any ID, data type, option meanings, project/board/issue-type applicability, units and sample values. Blank columns remain unknown. Map these to the logical concepts below; not every provided field must be fetched.
2. Inspect the deployed Jira product/version and existing adapter. Use the established authenticated HTTP client/PAT validation path. Read field metadata using a supported endpoint such as Data Center `GET /rest/api/2/field`; verify support on this deployment. Metadata may include `id`, `name`, `custom`, `schema.type`, `schema.items` and plugin type. The endpoint is illustrated in the [Jira 8.8.1 REST reference](https://docs.atlassian.com/software/jira/docs/api/REST/8.8.1/); this is not a claim that this installation runs that version.
3. If an explicit ID is supplied, verify its existence and shape. If only a name is supplied, find exact candidates and inspect the catalogue meaning, schema and permitted project/issue-type context. Similar/fuzzy matches are candidates only. Two plausible candidates produce `ambiguous_mapping`, not an arbitrary first match. Name changes do not silently rebind an already validated ID.
4. Use representative authorized issues from the relevant project/types to inspect sanitized field values, including non-null, null, missing and multi-valued cases. Where history matters, inspect at least one changed value and its changelog identifiers. A successful metadata lookup is not proof that a field applies to every issue or exposes history.
5. Verify actual API request/response shape: the field ID in the `fields` request, JSON access path, scalar/object/array representation, option IDs, units, and whether changelog uses `fieldId`, a system identifier or a label. Capture redacted fixtures without PATs, private prose or unnecessary user details.
6. Produce a mapping ledger with resolved/unresolved/unsupported status, evidence fixture, field/option/type/status IDs, scope, temporal coverage and the metrics enabled. If metadata/context APIs are unavailable to the user, report `metadata_unavailable` or `not_authorized`; do not request admin privileges or use unsupported internal APIs automatically. Continue supported paths.
7. Validate and version the registry. Register only safe parser kinds and value maps; do not evaluate code/formulas from the file. Publish the mapping revision with affected analysis outputs. Never change mappings underneath an immutable report or reuse a cached analysis computed with another version.

### Minimum mapping ledger columns

| Column | Required content |
| --- | --- |
| `logical_key` | Stable application concept, e.g. `story_points` or `acceptance_state` |
| `source_file_ref` | Actual file/sheet/row or section; catalogue version/digest |
| `jira_instance_scope` / `project_ids` / `board_ids` / `issue_type_ids` | Applicability; unknown is explicit, not assumed global |
| `source_kind` | Standard field, custom field, sprint resource, issue link, changelog, portal human record, or separate integration |
| `field_id` / `display_name` | Validated physical field ID plus human label; absent IDs remain null |
| `response_path` / `schema` / `parser_kind` | Path segments and validated scalar/option/array/user/link/date/number representation |
| `value_map` / `units` | Option/status IDs to app meaning, unknown values, measurement units/calendar |
| `history_identifiers` / `history_parser` | Verified field IDs/system tokens and only unambiguous label fallbacks; raw/fromString parsing rules |
| `time_basis` / `coverage` | Available now, at start, at first entry, at close/removal, or assessed after close; evidence boundaries |
| `required_for` / `missing_behavior` | Dependent metrics and which become unavailable if missing |
| `validation_status` / `evidence_ref` / `mapping_version` | Pending/resolved/ambiguous/unsupported, sanitized fixture reference and immutable version |

### Logical concepts and feature dependencies

Physical fields are deliberately left to the catalogue/metadata step. A custom-field label is never a metric definition by itself.

| Logical concept | Likely source to verify | Normalized shape / temporal requirement | Dependent behavior when absent |
| --- | --- | --- | --- |
| `issue_id`, `issue_key`, `summary`, `project` | Standard issue response | Stable ID + current key alias; historical summary when available, otherwise labelled collected text | Missing issue identity invalidates that record; do not silently drop it from exact whole-sprint totals |
| `sprint_id`, state, actual start/close, goal | Sprint resource plus verified start-event evidence | IDs, closed state, timezone-aware instants, goal text/source time | Non-closed sprint rejected; missing boundaries suppress exact historical metrics; missing goal text shown as not recorded |
| `sprint_membership` | Sprint custom field/resource and complete membership events | Ordered set-of-sprint-ID changes, not one display string | Baseline/added/removed/carryover facts need historical membership; current membership alone is insufficient |
| `status`, `issue_type` | Standard fields and histories with configured ID mappings | Canonical status/type IDs and labels at required boundaries; separate Done/Review/Testing/started/unknown mapping | Cycle and exact closing outcomes unavailable for unknown required mappings; preserve unknown issue rows |
| `assignee` | Standard user object and assignment events | Existing resolver's canonical principal; at start/close/removal/completion as available | Unknown history means unknown attribution, not automatically Unassigned; role summaries show coverage |
| `story_points` | Verified configured estimate custom field | Finite nonnegative numeric or null; start/entry and close stored separately | Count metrics remain usable; missing/invalid estimates make point coverage partial or unavailable |
| `application` | Verified custom field | Option ID/label or array as actually supplied; preserve cardinality | Application grouping unavailable; no effect on total issue count |
| `epic_relation`, `feature_key` | Verified epic/parent/custom/link sources | Stable issue references and hierarchy type; canonical relation with collection/boundary provenance | Feature grouping unavailable; do not assume Epic Link and Feature Key are identical |
| `goal_link` | Verified field/link or portal association | Explicit issue-to-sprint-goal links; effective/recorded timestamps | Goal-linked metrics unavailable until linkage coverage is known; do not infer from text/epic membership |
| `acceptance_state`, `acceptance_evidence` | Verified structured field(s) or portal record | Explicit accepted/pending/rejected/not-ready/not-recorded map, author/time/evidence | Done metrics stay independent; acceptance absent is not rejected or accepted |
| `scope_change_reason` | Verified field/event record or portal note | Reason with associated membership event when known and recorded time | Reason coverage visible; current reason does not explain every historic add/remove event |
| `blocked`, `blocker_reason`, `dependency` | Verified flag/status/link/record | Boolean or explicit state mapping; unioned intervals; linked issue/team/owner | Point-in-time flag can show blocked at close if reconstructed; blocked duration requires intervals; linked issue existence alone is not proof of blocking |
| `work_category` | Verified category field/tag mapping | One primary category or explicitly overlapping multi-category representation | Unknown category retained; do not infer technical debt/feature/support from summary text |
| `priority`, `severity` | Standard priority / separately verified severity | Distinct mapped IDs/labels with relevant time basis | Optional quality/context columns unavailable; priority and severity are not interchangeable |
| `reviewer`, contributors, testing/support activity | Verified custom user fields, events or separate integration | Source-linked activity records and canonical principals | Contribution remains assignment context; no invented collaborator credit from comments |
| `created`, `resolution`, releases/defect links | Standard fields plus verified transitions/deployment links | Timestamped records; resolution timestamp alone may not equal final Done transition | Cycle uses status history; release quality and escaped defects unavailable without attribution/window evidence |
| `comments` | Existing paginated comment component | Created/updated timestamp and visibility; relevant-comment definition/version and sprint-window scope | Missing permission/history not zero comments; comment content edited later cannot be claimed as at-close text |
| `capacity` and action records | Portal human records or explicit external source | Team availability units/period; owner/due/status/complete time | No inferred effort, capacity or utilization; action status is current as of observation time |

Each metric declares its own field/history dependencies. Block only those metrics whose required input is missing. A field that Jira marks required on a create screen is not necessarily required for every analysis metric.

### Versioned registry shape (design example, intentionally unresolved)

This is a shape example, not usable deployment configuration. IDs/names must be filled from the user's file and verified responses. Prefer JSON or the project's existing configuration mechanism to avoid a new configuration-parser dependency.

```json
{
  "schema_version": 1,
  "mapping_version": "pending-catalogue-validation",
  "catalogue_source": null,
  "jira_instance_scope": null,
  "project_ids": [],
  "board_ids": [],
  "fields": {
    "story_points": {
      "source_kind": "custom_field",
      "field_id": null,
      "display_name": null,
      "response_path": null,
      "parser_kind": "finite_nonnegative_number",
      "units": "story_points",
      "value_map": {},
      "history_identifiers": [],
      "time_basis": ["start", "first_entry", "close_or_removal"],
      "required_for": ["planned_points", "completed_baseline_points"],
      "validation_status": "pending",
      "missing_behavior": "disable_dependent_point_metrics"
    }
  }
}
```

Store safe paths as segment arrays (for example `["fields", "<validated-id>"]` after resolution), not arbitrary executable expressions. Implement an allowlisted extractor/parser registry. Never use `eval`, dynamically imported functions or user-supplied JQL fragments from this file. For issue searches, request deduplicated validated IDs needed by enabled components; avoid `*all` by default. Optional bad-field failures must be isolated and surfaced without losing core data, with bounded retries through the existing HTTP client.

### Parsing, history and missing-data rules

- Distinguish **missing key**, **present null**, **empty collection**, **zero/false**, **not applicable**, **invalid shape**, **not authorized**, **unsupported history** and **partial history**. The backend records a reason code; the UI explains it in plain language. An absent field cannot reveal whether it was unset or denied without further evidence.
- Numeric parsers reject booleans, NaN/infinity and incompatible units; preserve decimal points and null. Numeric strings are accepted only when the documented adapter explicitly supports that form. Do not parse `3 days` as story points.
- Option objects keep their stable ID and human label. Multi-selects/user arrays preserve all entries; do not take only the first item. Cascading options preserve parent/child paths. Unknown IDs remain Unknown and visible in coverage, rather than mapped by text similarity.
- User values go through the existing identity resolver; display-name equality cannot merge people. Date-only values and timestamp-with-offset values remain distinct; parse timestamps to UTC and display board timezone. Date-only fields cannot supply a precise transition instant.
- Sprint fields may have different DC/plugin shapes: validate a parser for observed objects, lists or legacy serialized values. Do not use generic regex on arbitrary text and silently claim complete membership history. Multi-valued application/work-category grouping must state when groups overlap and totals are non-additive.
- Changelog matching prefers validated `fieldId`/system tokens. Label aliases are allowed only when confirmed unique for that instance/context/version. Parse raw before/after IDs and labels using the field's actual schema; `fromString`/`toString` may be display labels and may not contain a recoverable structured value. Preserve incomplete/ambiguous events and mark dependent reconstructions unavailable.
- Full changelog pagination is an adapter capability to verify, not an assumption. Reuse pagination guards and reject gaps, repeated pages, invalid event times and ambiguous ordering. A current field plus a truncated history cannot establish start/close values.
- Mapping validation does not establish historical coverage. Reconstruct required fields using a known baseline or complete rewind from a known collected state. Newly added configuration cannot recover events Jira never recorded. Give goal/acceptance/feature/reason values the same temporal discipline as status and estimates.
- Store normalized logical fields under neutral names, with original field ID, mapping version, source revision, extraction time, time basis and coverage. New metric/UI code must not read `customfield_*` directly. Keep any legacy aliases isolated at an explicit compatibility boundary and covered by tests.
- Mapping changes produce a new candidate analysis revision/cache key and a clear configuration-change reason. Preserve prior published reports and human records; keep current permissions effective for every read/export. Do not recompute historical values silently using today's renamed option semantics.

### Mapping tests and ready-to-enable checklist

Required fixtures: duplicate names/different IDs; renamed field with same ID; project/type-specific field; ID in catalogue not found; missing metadata access; scalar/null/missing/zero; number-as-string/invalid number; single/multi/cascading options; canonical users with renamed aliases; issue/link hierarchy; sprint field variants; changed point ID in changelog; renamed/ambiguous history label; empty versus truncated history; removed/re-added membership; option deleted after close; goal/acceptance field updated after close; optional field failure while core tickets load; cache invalidation on mapping revision.

Before enabling a mapping, the ledger must identify the physical field/source and scope, prove its parser against sanitized responses, prove any required historical reconstruction, list affected metrics, and include passing tests plus a zero/missing/permission behavior. A production report shows configuration/coverage gaps instead of fixture values. Pending catalogue entries remain explicitly unresolved in the handoff ledger.

## 17. GPT-sol implementation handoff and completion contract

### Inputs and boundaries

Required inputs are this document, the existing repository, and the user's separate field catalogue when attached. The interactive prototype and REVIEW.md are behavior/layout references with synthetic values. Source priority: the latest explicit user instruction, this closed-sprint specification, validated catalogue/deployment semantics, then existing compatibility constraints. Earlier active-sprint assets and prototype snapshots are superseded. Do not build a new project or copy the static prototype into production as a replacement for the Flask feature.

Keep Flask/Jinja/vanilla JS, SQLite WAL, existing source/view/grant scoping and one supervised worker. No AI services, credentials, SDKs, prompts, embeddings or external model calls. Jira operations remain read-only; human assessments/actions are portal writes. Keep unrelated features, authentication and compatibility routes working. Start with private review records under current ownership; team sharing and external release/contributor integrations remain explicit later scope.

### Repository implementation map

| Files / area | Required work |
| --- | --- |
| `app/config.py`, `app/core/config_validation.py`, `app/core/dependencies.py` | Load/validate versioned field mapping and retain three legacy environment inputs; avoid hardcoded new deployment IDs |
| `app/services/sprint_viewer_service.py` | Registry-based field selection/extraction, closed-only catalog compatibility, capability-aware history adapter, isolated legacy aliases |
| `app/integrations/jira/pagination.py`, `identity.py`, existing HTTP client | Reuse bounded pagination, canonical identity and authenticated retry/error handling; extend only when necessary with tests |
| `app/features/automation/sprint_viewer/jobs.py` | Required/optional field dependencies, normalized event ingestion, complete revision/fence checks, independent publication and bounded history/trend work |
| `calculations.py`, proposed `analysis/*` modules | Pure historical populations, covered metrics, rules, exact issue cohorts and comparable trends; isolate existing metric outputs for compatibility |
| `models.py`, `repository.py`, `schemas.py`, migrations | Versioned analysis/config/evidence, historical projections, owner-scoped human records, optimistic concurrency, indexes and safe migration |
| `routes.py`, route registration / `docs/routes.md` | Authorized reads/writes, closed-sprint validation, allowlisted filters, consistent exports, safe error envelopes and compatibility coverage |
| `app/templates/automation/sprint_viewer.html`, `app/static/js/sprint_viewer.js`, proposed split JS/CSS | Closed-only shell, five role analyses, shared tabs, historical grouping, exact drill-down, progressive loading, accessible dialogs and responsive tables |
| `tests/test_sprint_viewer_service.py`, `tests/test_sprint_viewer_browser.py`, relevant route/hardening tests | Add fixtures before behavior changes; extend backend and real rendered interaction checks |
| `docs/env_reference.md`, architecture/operations docs | Registry input, mapping validation, missing/history states, worker operation, rebuild/recovery and rollout/rollback instructions |

Create focused modules such as `analysis/field_registry.py` and `analysis/normalization.py` if they fit the feature structure. Final names may follow repository conventions, but there must be a single normalization contract reused by all import paths.

### Implementation sequence and deliverables

1. **Baseline and field ledger.** Read repository instructions, route/architecture docs, service/job/repository flow and existing tests. Record current behavior and tests. Inspect the user catalogue if available; produce the section 16 ledger and sanitized fixtures. If absent, build the registry contract and mark entries pending without inventing IDs. Verify closed-sprint catalog selection and current/prior-year behavior.
2. **Normalization and historical evidence.** Add mapping/parsing tests first; implement registry-driven requested fields, immutable normalized values, status/assignment/membership events and per-field coverage. Discover removed issues via authorized historical sources. If an exact population cannot be proven, return unavailable for affected metrics rather than publishing a misleading total. Preserve core usability and job fencing.
3. **Metrics and rules.** Add the section 6 edge-case fixtures, then pure metrics, evidence cohorts and versioned rules. Reconcile original/added/removed/completed/unfinished partitions. Keep estimate movement separate. Validate cohort/export membership, small samples and trend comparability. Freeze algorithm/mapping/calendar versions.
4. **Server API and human records.** Implement view-scoped responses, evidence query handles, covered issue/timeline/trend reads and owner-scoped review writes. Add migration and authorization/conflict/idempotency tests. Keep all credentials out of payloads/logs/fixtures. Do not weaken grants to enable collaboration.
5. **Production UI.** Implement the historical shell and distinct role views from sections 4–5 in the existing app. Preserve key/summary/type/status/estimate/feature/comment context and historical developer grouping. Enable user identity selection correctly; replace sample people, dates and all literal metrics with API values. Keep optional tabs/sections honest when unavailable. No active workspace or mode toggle.
6. **Integrate and verify.** Run unit/integration/browser checks and the role scenarios. Validate not-closed input, empty/missing history, reassignment, changes after close, slow enrichment, access expiry, conflicting edits, small screens and filtered exports. Exercise actual Flask-rendered pages with mocked Jira fixtures; the design preview alone is insufficient.
7. **Handoff and rollout readiness.** Supply changed-file summary, resolved/pending mapping ledger, implemented feature matrix, migrations, commands/results, test evidence and remaining limitations. Keep a feature flag and backward-compatible read path; prepare rollback. Do not claim completion while a required section is a placeholder or while fixture data remains in production. Deployment and shared-record rollout follow the project's normal process and task authorization.

Release A includes role sections with real supported facts or explicit unavailable states. Release B adds event-heavy flow/trends as prerequisites permit. Release C integrations are not required for the baseline implementation. If the implementation task requests the whole supported historical scope, continue through Release B; document a specific unavailable-source blocker rather than quietly dropping a defining role section. WIP/burnup may remain unavailable until complete event coverage exists.

### Response and interaction contracts

Use existing `json_ok`/`json_error` envelopes. The analysis payload contains granted `view_id`, closed `sprint_id`, snapshot/generation, analysis/mapping/calendar versions, collection/close times, overall component states, shared metrics, role section descriptors and field/rule coverage. A metric object must contain:

```text
metric_id, availability (ready|partial|unavailable|pending),
value, numerator, denominator, unit, cohort_label,
eligible_count, measured_count, exclusion_counts, reason_codes,
time_basis, evidence_ref, input_revision_ids, calculation_version
```

Unavailable/pending values are null with a reason, never zero. Partial values explicitly describe the measured subset and may not masquerade as whole-sprint ratios. Do not expose private denied issue IDs in exclusion lists or diagnostics. `evidence_ref` is an opaque reference bound to the same authorized report revision; server-side membership is authoritative.

Issue responses contain stable issue identity, display fields, explicit boundary basis per historical field, typed coverage, page metadata and query/evidence context. A metric click replaces incompatible table focus/search/evidence and resets pagination, while leaving role/shared totals unchanged. Additional user filters then narrow the evidence with visible chips. A response for another sprint/revision/request sequence must not overwrite the selected table. Export resolves the same population server-side and excludes unauthorized records.

Configuration gaps are returned per concept/metric with reason codes from section 16. Suggested role metrics are layout metadata referencing shared calculation IDs, not independent calculations per role. Status-to-Done/Review/Testing and started-stage mappings use verified IDs and versioned configuration; unknown states remain visible. Role preference is not a server authorization role.

Human record payloads include title/state/note as appropriate, source evidence reference, owner, due date, expected revision and idempotency key. Validate maximum lengths, required owner/title/date and allowed enum values. Use proper CSRF handling in production. Record author and server timestamps; conflicting updates return the existing conflict convention without losing the client draft. Goal assessment is explicit and never auto-selected from metric values.

### Tests and commands for the implementing agent

The repository requires behavior tests before changes. Use the existing `.venv` and test configuration. Example commands from the repository root:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_sprint_viewer_service.py tests/test_config_validation.py -q
.venv/Scripts/python.exe -m pytest tests/test_sprint_viewer_browser.py -q
.venv/Scripts/python.exe -m pytest tests/test_route_contract.py tests/test_production_hardening.py -q
.venv/Scripts/python.exe -m pytest -q
node --check app/static/js/sprint_viewer.js
git diff --check
```

Add new metric/normalizer/route tests to the appropriate command scope; run syntax checks for any new JS modules as well. The full suite is the final integration check after relevant tests pass. These commands are prescribed for the future implementation, not claimed as run for this design revision. Use disposable databases for migration tests. Determine the current Alembic head using the project's existing Flask setup, generate a new additive migration and test upgrade against a representative prior schema. Do not run migrations against the user's database merely to validate the plan. Rollback must preserve review records and older published generations; do not use table drops as routine rollback.

Required additional assertions: no active workspace in the rendered feature; active/future sprint rejected server-side; duplicate field names never choose arbitrarily; configured estimate ID works in both live extraction and history; null/zero/denied remain distinct; unsupported optional fields leave issues usable; post-close edits do not contaminate historical fields; all role/evidence/export counts reconcile; grant expiry blocks reads and exports; browser displays no sample names/data in production.

### Definition of done

- Closed-sprint-only scope is enforced in UI, report creation/import and tests. Historical developer grouping/contribution remains; no active workspace/code path is introduced.
- All five role views deliver their specified analysis using real normalized data or accurately explained unavailable inputs. Shared totals, cohort definitions and privacy scope remain consistent.
- The actual user catalogue is traceable in a versioned mapping ledger. Every enabled field parser and required historical mapping has sanitized fixture evidence and tests. Pending mappings are explicitly reported, not guessed.
- Backend/frontend contracts, migrations, permission boundaries, progressive loading, error states, persistence, exports and historical edge cases pass the required checks. Runtime has no AI integration or synthetic production fallback.
- The final implementation report identifies what works, what was tested, unresolved source limitations, configuration needed and safe rollout/rollback steps. Completion is not inferred from a working static preview.

### Copyable implementation prompt

> Implement the past-sprint analysis feature in this repository according to `docs/plans/sprint-viewer-v2.md`, especially sections 16–17, using the separate Jira field catalogue attached to this task. This feature covers closed sprints only: no Active sprint section, active/past toggle, active board or live sprint workflow. Retain historical developer grouping and implement distinct Team, Developer, PO / BA, Scrum Master and Engineering Manager views, deterministic metrics/suggestions, evidence drill-down and human review records. Use the existing Flask/Jinja/JavaScript/SQLite worker architecture and preserve compatibility routes and authorization. Resolve and validate field IDs, shapes, option meanings and changelog identifiers from the supplied file and deployment evidence; do not guess IDs or equate display names with unique fields. If the file is missing or mappings are unresolved, continue independent implementation with tests and explicit unavailable states, and report exactly which deployment mappings are still required. Read repository instructions, add behavior tests first, work through the implementation phases, and run the prescribed checks. Use `docs/designs/sprint-viewer-v2/index.html` and `REVIEW.md` as synthetic visual/interaction references only; do not transfer fixture data into production. Make no AI integrations or Jira writes. Finish with the implemented feature matrix, resolved/pending mapping ledger, migrations/configuration instructions, tests/results and remaining source limitations. Older active-sprint proposals are superseded by this plan.
