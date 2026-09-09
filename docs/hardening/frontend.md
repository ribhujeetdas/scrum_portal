# Frontend behavior, tests and acceptance

This is the third part of the [implementation plan](README.md). Follow [backend contracts](backend.md) for exact API states and authorization. All product decisions are settled: SQLite only, fresh Jira access checks, existing metric formulas with time-basis labels.

## F01. Preserve the interface while changing its behavior

Keep current template paths, visual layout, Bootstrap version/appearance, sidebar, project/board/sprint controls, Refresh Sprints, Fetch Issues/Start Over, accordion, metric cards, Jira links and XLSX action. Small progress, unavailable-state and time-basis text is required for truthful behavior; a visual redesign is not in scope.

Maintain DOM IDs used by existing renderers and tests. Do not move Jira/SQL/worker implementation detail into user-facing copy. Preferred labels: “Loading tickets…”, “Checking Jira access…”, “Calculating metrics…”, “Historical values unavailable”, “Metrics could not be loaded. Retry”, and “Jira points at collection time”. Technical request IDs may appear in error details for support.

Existing facts to preserve:

- Page template is `app/templates/automation/sprint_viewer.html`, stylesheet is `app/static/css/sprint_viewer.css` plus current shared styles, and feature entry is `app/static/js/sprint_viewer.js`.
- `app/static/js/app.js` discovers `data-feature-script-src`; it already deduplicates script sources within its initialization. Keep the normal fetch/session/toast helpers.
- Current grouping includes subtasks; standard-ticket quality and scrum metrics exclude them. Do not accidentally make header totals disagree by changing which set they count.
- Start Over already asks the user to reset displayed data. Keep the same action/confirmation unless a focused accessibility correction is necessary. It resets display, not database snapshots.
- The current export is a generated XLSX workbook, not CSV. Preserve its sheets, columns and type handling; add provenance/availability notes without renaming existing fields arbitrarily.

## F02. JavaScript ownership and entry points

Use native modules without bundling production JS. Stable `sprint_viewer.js` is a small loader that imports `./sprint_viewer/index.js` once, catches load errors safely and registers an initialization marker on the page element. Index exports `initSprintViewer(page, api)` and an explicit dispose function for tests/navigation. Avoid a global mutable singleton shared across multiple page instances.

| Module | Responsibilities |
| --- | --- |
| `index.js` | Initialize once, wire events, call state/API/render services, cleanup. |
| `state.js` | Immutable state transitions, current action generation, component/access states, revision guards. No fetch or DOM. |
| `api.js` | portalApiFetch integration, response schema/HTTP status handling, abort/deadline and one poll loop. |
| `render.js` | DOM creation with textContent/createElement, incremental group rows, badges/help text, accessibility. No requests. |
| `export.js` | Pure workbook/XML/ZIP construction adapted from current code; no DOM/network dependency. |
| `export.worker.js` | On-demand worker for workbook generation, emits transferable bytes/progress/errors. |

If native modules require loader changes, limit them to the feature and browser tests. Do not convert the entire app or inline new script blocks into templates. Do not preserve brittle source-text tests by leaving dead functions/import strings behind.

## F03. State contract

Keep one active view state:

```text
selection: projectKey, boardId, sprintId
actionGeneration: monotonically increasing local integer
clientActionId: random UUID for this explicit action
snapshotId, serverGeneration, responseRevision, viewId
catalog: idle/loading/ready/empty/failed
core: idle/queued/running/ready/failed
history, comments: idle/queued/running/ready/unavailable/failed
metricCategories: state/revision for O, CO, TC, A, R
metrics: idle/queued/running/ready/failed
access: component-specific pending/granted/denied/unavailable + expiry
data: immutable published input revisions and normalized issue/group maps
export: unavailable/ready/authorizing/building/failed
controllers/timers: current view only, disposed on reset
```

Server states and access states are separate: ready data with pending access is not displayable. `null`, absent and unavailable metrics must render a placeholder/label, not `?? 0`. Only a complete numerical zero renders 0.

### Event flow

1. Project change clears board/sprint selection and current view state, aborts old requests and fills boards from existing page data.
2. Board change starts catalog request and disables only dependent sprint controls. An empty catalog shows “No matching closed sprints”; it is not an error or auto-refresh loop.
3. Refresh Sprints POST uses refresh=true and a new action ID. Keep any previously authorized catalog usable while refresh status is shown, but clearly indicate it is the last successful list. Failure keeps that list and offers retry; no report snapshot is rebuilt.
4. Fetch Issues captures immutable board/sprint values, creates one clientActionId, increments actionGeneration, sets Start Over mode and calls issues once. Do not immediately launch a second redundant metrics import: the backend pipeline queues missing categories. The separate metrics endpoint remains for compatibility/retry consumers.
5. On 202, show processing/access progress and start one poll loop. On authorized core ready, fetch bounded core data/group summaries, render tickets, and enable ticket links, accordion and Start Over immediately. Metrics never hold that lock.
6. History/comments/category publication increments responseRevision. Read only changed authorized components, then update affected statistics, principal groups and cards. All async handlers verify local generation + snapshot/server generation + expected revision before applying changes.
7. Categories can complete out of order. Render only values whose dependencies are ready. Derived metrics are never computed from a partially filled `{}` default on the client.
8. On terminal metric failure, retain core and show inline Retry. Clicking Retry posts once for failed component(s), not issues again. Previously ready categories are reused.
9. On Start Over, confirm existing reset action; increment generation first, abort requests, stop polling, terminate export worker, discard in-memory data and reset selectors. Background jobs may continue for reuse; do not claim AbortController cancels them.
10. On session expiry/access denial, immediately prevent further export, stop data requests, clear protected results and use existing session/login UX. Authorization-expiry renewal is an explicit POST; polling is read-only and never extends the absolute session lifetime.

### Polling algorithm

Only one status request in flight per active view. Schedule the next after the previous completes, not with overlapping setInterval calls. Start at 1.5 seconds, increase to 2, 3 and 5 seconds if nothing changed, add bounded ±20% jitter, honor Retry-After up to 30 seconds. Reset backoff on a meaningful revision/state change. If the page is hidden, slow to 10 seconds and never grant more access due to hidden polling. On focus, check current authorization before rendering protected stored content.

Poll attempts are reads and never create a job. Stop on all required terminal states, reset, navigation or auth loss. A component failed/unavailable is terminal until explicit retry or required access renewal; no endless polling for permanent capability failures. A lost network connection shows a recoverable inline status and bounded backoff, not repeated toast spam. Browser fetch timeout is 15 seconds for short control/data/status APIs; a timeout does not mean the worker failed. All reattempted start/retry POSTs reuse the same clientActionId.

## F04. Rendering and metric dependencies

Create accordion headers for authorized groups immediately. Render rows on first expansion in batches of 50 using requestAnimationFrame or equivalent cooperative scheduling. Preserve current collapse/expand behavior. Store issues in a data map independent of the DOM; collapsed groups still count and export correctly. Large core datasets use the bounded issue-page API; fetching additional authorized DB pages is separate from re-fetching Jira data.

Group key is canonical principal ID or explicit unresolved/unassigned identity, not displayName or array index. Row key is Jira issue ID. When historical reconstruction moves a ticket to another principal, update the data model first, reconcile visible groups, preserve expanded groups that still exist and keep focus/scroll stable. Unknown historical identity is shown honestly rather than forcibly merged. Do not render two copies of one issue during regrouping.

Source scope-added keys are stored in state; apply stars when rows are created as well as when metric data first arrives. This prevents stars missing on groups expanded after metrics complete. Links use configured source URL and encoded validated issue keys, with safe external-link attributes. No innerHTML from Jira content.

| Card/data | Required ready inputs |
| --- | --- |
| Original commitment | O |
| Completed original | CO |
| Total completed | TC |
| Added scope + ticket scope stars | A |
| Removed scope | R |
| Completed added | TC + CO |
| Carryover / spillover | O + CO + R |
| Net scope | A + R |
| Predictability | O + CO |
| Delivery vs commitment | O + TC |
| Added scope % | O + A |
| Removed scope % | O + R |
| Scope change % | O + A + R |
| Ticket quality / work type | Complete core, plus history where historical fields are used; provisional labels otherwise |
| Relevant comments | Complete comment evidence + canonical team/historical identity + comment access grant |

The server supplies authoritative card values with field availability; this dependency table governs when it may publish them and what UI placeholders remain. The browser does not reinterpret the business formulas.

Use `aria-busy` on affected sections and a restrained `aria-live=polite` progress region. Spinner accessible text must reflect its section, not claim the whole page is locked. Do not rely only on red/green. Keep visible keyboard focus and avoid repeated live announcements for every poll.

## F05. Full XLSX export contract

Full report means all imported core ticket rows and complete five-category scrum metrics from the same snapshot generation. It does not mean unavailable Jira history can be invented. History/comments must be terminal: verified ready, or explicitly unavailable with current-fallback/unavailable labels. A transient failed/running component keeps export disabled until resolved or classified as genuinely unavailable by the server. Access-denied data is never exported.

1. Enable the existing Download Report action when backend export readiness is true, not merely when `report.metrics` is truthy.
2. On click, request fresh export-purpose access verification. Keep tickets usable while the action shows “Checking access…”. If permission changed, cancel export and clear withheld data.
3. Obtain immutable export manifest including snapshot ID, generation, core/history/comments/category/final revision IDs, allowed fields, availability warnings and fetched timestamps. Data page cursors bind to this manifest. Do not use unverified stale browser data merely because it was displayed earlier.
4. Fetch required authorized DB pages. If the grant expires midway, stop and reauthorize the same immutable manifest; do not mix a new generation into an old workbook. On denial, discard partial bytes.
5. Generate XLSX in the on-demand Web Worker from full data, never accordion HTML. Missing/unavailable fields are blank or labeled “Unavailable”, and current fallback columns/notes explicitly say so. Preserve existing sheet names/columns and add a provenance/availability section or sheet.
6. Preserve count/point rounding and current formulas; metric points label “At collection time”, verified ticket values “At sprint completion”. Include snapshot collection dates, access-check time and historical-fallback count. These are reporting details the user needs.
7. Encode all untrusted Jira strings as XLSX strings, not formulas. Escape XML special characters and invalid control characters correctly. Test values beginning `=`, `+`, `-`, `@`, apostrophes, ampersands, quotes, angle brackets, non-ASCII names and multiline summaries. Story-point cells remain numeric when finite.
8. Return transferable bytes to main thread; create/revoke Blob URL, trigger one download, terminate worker. Reset/navigation cancels generation without affecting stored snapshots. On error, restore action state and show one useful message.

Do not replace the existing exporter with a new runtime library unless a concrete correctness/performance failure requires it. Use `openpyxl` as the dev-only workbook verifier and Python zipfile/XML parsing for low-level escaping/type assertions; neither becomes a production dependency.

## T01. Test organization and fixtures

Place shared Flask/user/project/auth fixtures in `tests/conftest.py`; stop cross-importing helper functions from other test files as migrations grow. Use generated harmless Fernet keys, mock Jira/Tableau origins and isolated databases/log directories. Configure TESTING before constructing the app. Close logging handlers/SQLAlchemy sessions/connections in teardown so Windows files can be cleaned up.

Fixtures cover Jira DC issue/user/comment/changelog payload shapes, all five ScriptRunner categories, capped pages and definitive rule-create rejections. Include a source provenance note for sanitized real-format fixtures. Do not commit PATs, usernames from production, real comments or raw exports. Test services receive injected clients/clocks/sleep/jitter sources. Time-based correctness tests use controlled clocks, not long sleeps.

Unit tests use in-memory SQLite only where transaction concurrency is irrelevant. All queue, locking, migrations, backup, lease, multi-process and readiness tests use temporary file-backed WAL SQLite with independent connections/processes and the supported patched runtime. Never run concurrency tests against `sqlite:///:memory:` and claim production correctness.

## T02. Required regression cases

IDs below correspond to the master coverage table. Each may expand to parameterized cases; implementations may add meaningful tests but must not silently omit listed cases.

### Jira collection and identity

| ID | Setup and required assertion |
| --- | --- |
| J01 | Request 50/200; server caps to 2 with total 3 and isLast=false. Collect all 3 exactly once and sum 9, not 6. Apply to issues and metric categories. |
| J02 | Short page with false last flag, exact page multiple, zero-result total, missing total, known total, total as invalid type. Correct completion or explicit schema error; never infer completion from requested size. |
| J03 | Server repeats page, returns empty before end, moves offset backwards, changes conflicting duplicate record, or exceeds limits. Component never ready; bounded calls and safe error. |
| J04 | Same issue appears twice across pages with identical data. Deduplicate by ID, not key/summary; page offsets still advance by actual returned page length. Cardinality inconsistency fails/retries as defined. |
| J05 | Settings boards/board-projects and Tableau custom-view pages use server-returned page size and reach a view beyond the first capped page. Current/previous-year filter does not alter pagination counts. |
| J06 | Core payload excludes comment/changelog prerequisites; block comments indefinitely in a fake. Core still publishes and is renderable first. Comment pagination completes independently with bounded concurrency. |
| I01 | Current username E123 + historical stable key JIRAUSER123 for one verified person -> one canonical group; original synthetic double-group fixture is fixed. |
| I02 | Two distinct keys with same display name -> two groups. No merge-by-name. |
| I03 | Renamed user and reused/ambiguous username -> correct verified alias or unresolved result, never accidental merge. |
| I04 | Missing assignee, missing key, whitespace, comment username/key variation and unresolved historical display text -> explicit stable representation; true unassigned is separate. |
| I05 | Many tickets/comments for one unknown principal -> at most one lookup per unique unresolved reference per work unit; no N+1 identity requests. |
| I06 | Comment-author/team matching uses principal ID and cutoff; mismatched string namespaces no longer lose relevant comments. |

### History and metrics

| ID | Setup and required assertion |
| --- | --- |
| H01 | Post-sprint status/assignee/point changes -> reverse to completion values in descending order; changes at cutoff are treated consistently as not after cutoff. |
| H02 | Historical from=null assignee -> unassigned; from points=0 ->0; from points=null ->unestimated. Never fallback through boolean `or`. |
| H03 | Complete empty history -> no changes, current values valid at cutoff. Missing/truncated nonempty history -> explicit fallback/unavailable. |
| H04 | Changelog total > returned count -> fetch supported remaining pages or mark unavailable; no fake ready history. |
| H05 | Date formats with UTC offsets/Z, invalid dates and missing completion cutoff -> deterministic quality flags; no silently trustworthy reconstruction. |
| H06 | Shared sprint/history membership with structured/comma/list IDs -> correct carryover evidence; incomplete history ->unknown; digits in sprint names do not invent IDs. |
| H07 | History completes after core: tickets regroup once, totals/work mix use one revision, and relevant comments recompute with the same canonical team. |
| MET01 | Golden fixture O=40/10, CO=32/8, TC=44/11, A=12/3, R=4/1 ->80% predictability, 12 completed-added points, 4 carryover points, 8 net-scope points; aliases match old supported output. |
| MET02 | Removed issue absent from core is included in R and relevant O input; DB metric result equals the complete five-query fixture. |
| MET03 | One category fails -> dependent values null/unavailable, independent cards ready; retry reuses other ready categories. No zero-default fabrication. |
| MET04 | Zero denominator/zero-result category, null/invalid/NaN/Infinity points, negative net scope and >100% delivery -> explicit preserved rounding/formulas and warnings. No invalid JSON numbers. |
| MET05 | Ticket has 5 points at sprint completion, current metric search returns 8 -> ticket5/metric8 retained and labeled. A calculation-version change cannot reuse incompatible final results. |

### HTTP behavior and mutation safety

| ID | Setup and required assertion |
| --- | --- |
| HTTP01 | App configured retries0/timeouts/custom statuses; run worker with no Flask context ->exact injected config survives. |
| HTTP02 | Connect/read failures, 429 Retry-After, successive503 then200 ->bounded explicit attempts, deadline/backoff, per-attempt timing and released slot. |
| HTTP03 | Slow trickle, oversized JSON/CSV, invalid JSON and unclosed error response ->bounded failure, response/session closed, no indefinite wait or unbounded allocation. |
| HTTP04 | N=2 and N=1000 issue extractions ->one request service, no HTTP clients constructed by pure calculations; injected client ownership respected and no shared sessions across lanes. |
| HTTP05 | Rule POST times out/returns500 after possible creation ->one mutation attempt, no actor or project fallback, operation unknown. |
| HTTP06 | Typed definitive actor/identifier rejection ->only approved bounded fallback; generic string error does not authorize fallback. |
| HTTP07 | Same idempotency key/fingerprint concurrent actions ->one logical send; different payload same key ->409; unknown outcome retry never silently resends. |
| HTTP08 | Off-origin/self URL/redirect/context-path escape rejected before credentials sent; valid configured context path and enterprise CA work. GET read retry remains supported for Jira and Tableau; sign-out cleanup is attempted appropriately. |

### Persistence, worker and APIs

| ID | Setup and required assertion |
| --- | --- |
| DB01 | First miss imports; later completed read returns identical authorized DB data without ticket-field/comment-enrichment/metric recomputation calls. Count authorization calls separately. |
| DB02 | Empty ready core/catalog/category ->subsequent hit, no endless new import. |
| DB03 | Same source/board/sprint for two users/PAT scopes ->separate results and no cross-read/dedup. Different boards/sources/versions remain distinct. |
| DB04 | Crash after staged page ->no complete snapshot; restart into new revision, no duplicate memberships, previous published components retained. |
| DB05 | Explicit refresh/rebuild fails ->old catalog/active snapshot survives; no deleted-before-fetch window. |
| DB06 | Old-generation response cannot combine with new metrics; manifest/page cursors pin revisions. All-or-nothing publication and empty sentinel verified. |
| DB07 | Concurrent refresh/initial catalog load ->one active revision/job, uniqueness conflict reread, no generic500 for expected races. |
| W01 | Multiple processes request same candidate concurrently ->one series/candidate and active job via SQLite constraints. |
| W02 | Accidental second worker process ->leader rejection/standby exit; expired leader takeover increments epoch. |
| W03 | Old leader/job resumes after lease expiry ->all late writes/publication rejected by fence/epoch. |
| W04 | SIGTERM/restart, kill between stage/publish, lost heartbeat ->recoverable read jobs, no orphan permanently-running state. |
| W05 | Long comments + metrics + fresh core ->core/access lane available; global slots <=4 and background <=2 across all processes. |
| W06 | Normal continuation/yield does not consume retry attempts; actual transient failure does, with maximum combined attempt budget. |
| W07 | Same-file web reads and concurrent batch writes with WAL ->bounded busy handling; no shared sessions, write transaction never spans HTTP wait. |
| W08 | Disk full/DB unavailable ->readiness/admission fail safely, no automatic deletion of successful snapshots. |
| W09 | User disabled/PAT changed/board deleted mid-job ->no next batch or publication under revoked epoch. |
| API01 | Canonical and legacy endpoints return same auth/error/ready/202 contract; additive processing does not masquerade as completed data. |
| API02 | Status GET repeated ->no new jobs; one explicit POST starts/retries, logical limits shared across aliases. |
| API03 | Scalar/list JSON, bool/float/negative/oversized IDs, wrong refresh type, invalid cursor/component ->safe4xx and zero upstream calls. |
| API04 | Missing/expired view, mixed generation/cursor, terminal unavailable and unknown IDs ->defined responses; no leaked error details or unbounded payload. |
| API05 | Refresh Sprints changes only catalog; Start Over never deletes data; retry failed metrics does not refetch core. |

### Security, migrations and operations

| ID | Setup and required assertion |
| --- | --- |
| SEC01 | Production placeholder/missing secret/Fernet key, enabled missing integration, unsafe URL/debug/host settings ->startup fails without revealing secret values; explicit dev/test profiles work. |
| SEC02 | Stale/missing/invalid login CSRF with otherwise correct credentials ->400, no login/session; response has fresh token, correct resubmission logs in. |
| SEC03 | Canonical and legacy form/API CSRF cases plus expired session ->appropriate HTML/JSON, no fallback bypass. |
| SEC04 | Already logged in user disabled/deleted ->next HTML/API/status/export fails authentication; malformed user ID never500. |
| SEC05 | Password/session epoch/PAT changes across two sessions ->old sessions/grants invalidated as required; polling cannot extend absolute timeout. |
| SEC06 | Saved board with unrelated supplied sprint ->rejected before fetch; no blank-metadata success. Shared sprint validated by association, not origin alone. |
| SEC07 | User A knows B's snapshot/view/job UUID ->404/no contents, including progress/errors/export. |
| SEC08 | New saved-report view ->fresh Jira identity/board/core visibility validation. Required issue ID missing ->withhold component; project permission alone never grants. |
| SEC09 | Removed-scope metric-only issue becomes inaccessible ->metrics/export withheld, authorized core can remain usable. |
| SEC10 | Comment restriction/deletion or unsupported history visibility ->stored sensitive count/history withheld; no automatic offline fallback on Jira outage. |
| SEC11 | Project/board/source/credential revocation during job/grant ->immediate local invalidation, no resurrected snapshot after re-add without new scope. |
| MIG01 | Empty file ->safe frozen bootstrap + forward upgrades, expected single head, repeat no-op. |
| MIG02 | Each known historical stamped revision ->correct remaining upgrades and preserved data. |
| MIG03 | Exact unversioned legacy head ->check output + explicit adoption, no blind stamp; wrong/partial schema ->abort with diff. |
| MIG04 | Existing encrypted PAT bytes, IDs, hashes, booleans/nulls and mappings unchanged through new migrations. |
| MIG05 | DB foreign keys actually on; user/scope/revision delete paths and cascades behave correctly under ORM and bulk actions. |
| MIG06 | Empty direct db-upgrade produces actionable setup-db instruction; deprecated init-db cannot create an unversioned current schema. |
| MIG07 | Backup during WAL writes restores to independent file with integrity/FK/revision checks; teardown closes connections on Windows. |
| OPS01 | Production starts with explicit SQLite absolute local path and approved runtime; in-memory/unsupported location/config rejected; no PostgreSQL dependency exists. |
| OPS02 | Waitress web and worker use same intended file/version/config; migration not run by every process; duplicate worker fenced. |
| OPS03 | Health does not call Jira or leak paths/secrets; stale worker blocks new admission appropriately but not safe complete reads. |
| OPS04 | Graceful shutdown/backup/restore and recorded rollback procedure work in a staging drill. |
| OPS05 | Trusted host/proxy/security-header configuration preserves login/session/Bootstrap UI and prevents spoofed forwarded-IP rate bypass. |
| OPS06 | Clean locked install on Windows and Linux CI targets succeeds; runtime excludes test/security tooling; dependency audit result recorded accurately. |
| OPS07 | Full functional suite and browser checks pass without real Jira/Tableau credentials or accidental standalone updater execution. |
| OPS08 | Rate limits across two processes, actual body limits without Content-Length, expired bucket cleanup, disk/WAL growth observations ->bounded behavior and no log-recursion flood. |
| OBS01 | Browser action ID ->request ID ->job ->category ->upstream attempts traceable without raw credentials/JQL/data. |
| OBS02 | Success/failure spans record durations, retries, bytes/pages, queue delay and DB lock wait separately. |
| OBS03 | Redaction tests cover Bearer/PAT/password/cookie/Tableau token and URL query/fragment fields, including client-log inputs. |
| OBS04 | UI ticket-ready/metrics-ready/export timings correlate with server evidence; no stale snapshot result emits a false success event. |

### Browser, export and performance

| ID | Setup and required assertion |
| --- | --- |
| UI01 | Core returns first, metrics delayed 30 simulated seconds ->accordion/link/Start Over usable while cards show progress; no page overlay. |
| UI02 | Metrics fail ->tickets retained, one inline retry, one failed-category retry request, no core reload. |
| UI03 | Reset/select new sprint while old response resolves ->no old DOM/data/control mutation; all old timers/controllers disposed. |
| UI04 | Multiple event triggers/feature loader attempts/double clicks ->one active flow and one logical import; no duplicate initialization. |
| UI05 | 401/403/expired grants/network failure/429 ->correct section state and retry cadence, no unexpected session extension/toast flood. |
| UI06 | 1000 tickets across many groups ->collapsed row DOM absent until needed; expand all progressively; stable focus, no duplicate rows, late scope stars applied. |
| UI07 | Actual browser accessibility checks for keyboard, aria-busy/live, unavailable states and reset dialog; current layout screenshots remain comparable. |
| EXP01 | Workbook parses; existing sheets/columns and all ticket rows included even when collapsed/not displayed, same snapshot revisions. |
| EXP02 | Missing historical/comment evidence ->honest fallback/unavailable fields and notes; no zero fabrication. Missing category/core ->export disabled. |
| EXP03 | Permission changes immediately before export ->fresh check prevents download; expired grant mid-page collection handled safely. |
| EXP04 | Unicode/XML/control/formula-like strings and finite/null points ->valid safe XLSX; no formula injection. |
| EXP05 | Export worker canceled on reset; Blob URLs revoked; large export does not freeze ticket interaction. |
| PERF01 | Service/client construction O(1) per work unit rather than O(issues); record counts using injected factories. |
| PERF02 | Page renders with 1 vs20 projects ->constant bounded queries for project/board list (one explicit project query plus select-in board query, excluding fixed auth work). |
| PERF03 | File-backed SQLite DB hit and status reads use intended indexes (`EXPLAIN QUERY PLAN`); no unnecessary joined loading of all projects on auth/status. |
| PERF04 | Representative 50/250/1000-ticket render, export and concurrent imports meet agreed targets or produce a precise bottleneck report; no unsupported speedup claim. |

## T03. Existing tests that must change intentionally

Do not delete or weaken tests simply to make the new code pass. Preserve their user-visible contract and update obsolete assumptions explicitly:

- `tests/test_session_and_navigation.py::test_login_recovers_from_stale_csrf_after_session_expiry`: currently expects302 despite stale token. Replace with SEC02's400/no-session then valid resubmit expectation.
- `tests/test_rule_copier_fallback.py`: current fake raises an untyped service error; change to typed definitive rejection for permitted fallback and add ambiguous-outcome no-fallback cases.
- `tests/test_phase3_shared_core_adoption.py`: checks source strings/import location. Replace/extend with injected-client ownership, shared transport and pure-calculation behavior; imports moving to integration adapters is allowed.
- `tests/test_phase4_frontend_modularization.py` and `test_phase8_canonical_route_migration.py`: currently search the single feature JS file for endpoint/export implementation strings. Include the ES module graph or assert real browser routes/behaviors. Keep stable entry, canonical URLs and legacy availability tests.
- `tests/test_phase7_database_performance.py`: keep existing timestamp/index/PAT checks, replace old request-local metric executor expectations with explicit policy propagation and durable-worker behavior. Existing PAT session reuse does not substitute for report-view visibility tests.
- `tests/test_phase6_feature_routes_and_failures.py` and its imported helper users: move shared fixtures into conftest, teach login helpers to create real auth sessions/epochs, cover direct and snapshot mode200/202 deliberately.
- `tests/test_sprint_viewer_service.py`: retain formula goldens, add identity/history/pagination regressions; wrappers can keep old class API while pure functions move.
- `scripts/smoke_check.py`: use explicit isolated configuration in CI. It currently constructs default app before TESTING; do not rely on that after production validation is hardened.

## T04. CI commands and stages to implement

Add pytest markers `integration`, `browser`, `performance`, `staging` and document their meanings. Integration includes file-backed SQLite; never hide it from the default required CI suite. Staging tests may require explicitly provided external capability fixtures/access and must be distinguished from offline tests.

Suggested CI sequence after dependency lock generation:

```text
python -m pip install --require-hashes -r requirements/dev-py312-windows.lock
python -m pytest -q tests -m "not browser and not performance and not staging"
python -m pytest -q tests/browser
python -m pytest -q tests/performance
python scripts/smoke_check.py --config test
python -m pip_audit -r requirements/runtime-py312-windows.lock
```

The commands above are for Windows; Linux CI uses the corresponding `-linux.lock` files. The implementer must add any missing CLI flag rather than assume it already exists. Use Python Playwright + pytest plugin in the dev lock and install its matching browser revision in CI explicitly. App JS remains native modules with no Node production dependency. Use browser download/cache configuration approved for CI, and record exact browser/runtime versions. Openpyxl remains dev-only. Generate lock files with the pinned pip-tools version, explicit Python/platform environment and hash output, then prove a clean install on each target rather than assume one platform's resolution covers the other.

Windows CI catches file locking/path/process cleanup; Linux CI catches deployment assumptions. Both use actual patched SQLite linked by the tested Python runtime. No Linux-only database backend is added. Collect failure artifacts only with synthetic data: screenshots, traces, test logs and sanitized request counts.

## T05. Performance experiments and success thresholds

Instrument before/after in the same environment. Benchmark offline fakes with controlled latency for deterministic ordering/call-count assertions, then use staging Jira for actual wall-clock results. Keep authorization time distinct from data-fetch time.

Required scenarios:

1. First-ever sprint: 50,250,1000 tickets, mixed subtasks, unknown identities and comment-heavy tickets. Record ticket-ready time, history/comment-ready time, metric-ready time, request/page counts, bytes, worker queue delay and DB writes.
2. Repeat completed snapshot: fresh authorized view, no ticket-field import or ScriptRunner recomputation. Measure fresh access-check cost separately; comment visibility checks may still call Jira.
3. Ten simultaneous viewers of the same user's snapshot: one import generation/job, multiple session-scoped access views as needed. Distinct users must not share protected data.
4. Ten simultaneous viewers of different sprints with two heavily enriched imports. Verify core/access priority, global Jira slots, SQLite lock wait/busy counts and stable memory.
5. Jira429/slow503, permission revocation, unsupported history, process crash and DB-busy simulation. Correct failure behavior is a success criterion; a fast incorrect result is failure.

Initial acceptance targets on the agreed local production-like host: p95 completed authorized DB data API response <=1 second for <=1000 tickets using bounded pages; core ticket interaction within2 seconds after core data becomes authorized/available; no dependency on completion of delayed metrics; no unexpected busy500; global Jira call limits respected; query/client-construction counts bounded as specified. Cold-import and fresh-authorization absolute times depend on actual Jira and must be baselined before setting an end-to-end SLA.

Capture host/runtime/dataset/concurrency, 5 warmups then at least30 measured samples for median/p95 where practical, absolute timings and call counts, not just percentages. Do not run a high-volume load against production Jira without an explicitly chosen test scope/window. Performance thresholds in CI should test algorithmic/request-count regressions and controlled timing order; avoid flaky strict millisecond assertions on shared runners.

## T06. Completion evidence and remaining external facts

For every coverage ID record implementation files/functions, regression test IDs, actual command/results and any limitation. The final implementation report must list:

- All milestones completed and any intentionally deferred product work (automatic freshness and historical formula redesign only).
- Exact dependency/Python/SQLite/browser versions and database schema head.
- Full suite, browser, concurrency, migration and backup/restore results.
- UI preservation evidence and slow-metrics/ticket-interaction proof.
- Cold/repeat request counts with authorization separated.
- Security corrections including CSRF, account/PAT revocation, cross-scope access and mutation unknown-outcome handling.
- Deployment facts not established locally: actual Jira capabilities/permission behavior, real concurrency capacity, service hosting and organizational recovery requirements.

A missing live capability/restore/load verification is a stated release limitation, not permission to mark that gate passed. A local implementation may be ready for staging without claiming production activation has occurred. The plan itself creates no deployment or live Jira mutation authorization beyond the user's implementation request.
