# Scrum Portal: P1/P2 implementation plan

Prepared 2026-09-09 for GPT Sol. This is an implementation specification, not evidence that the fixes have been implemented.

## 1. Read order and authority

Read this package in order:

1. This file: scope, decisions, coverage, work packages and deployment.
2. [Backend contracts](backend-contracts.md): persistence, transaction boundaries, Jira algorithms, worker, API and security contracts.
3. [Frontend and validation](frontend-and-validation.md): UI states, browser behavior, regression cases, acceptance and measurement.
4. [Sol handoff](SOL-HANDOFF.md): execution instructions and completion checklist.

The originating evidence is [the performance review](../../sprint-viewer-performance-review.md). This package supersedes that review's tentative implementation suggestions. User decisions in the current conversation supersede this package; record their effect before changing implementation. Paths below are repository-relative, rooted at `D:\WF\scrum_portal-main` in the reviewed workspace. Line numbers in the review are navigation aids only; locate functions again before edits.

Do not interpret a plan item as a discovered production exploit or a measured performance result. This review covers all P1/P2 items recorded in the originating review and the related call sites needed to fix them consistently across the application. It is not a claim that an exhaustive security assessment of every workflow has been performed.

## 2. Objective and boundaries

Deliver a functioning, tested application with:

- The existing Flask/Jinja/Bootstrap interface, navigation, Jira links, groups, metric cards, settings, Rule Copier, Tableau/TCI and full XLSX export preserved.
- Interactive tickets as soon as their core import is complete; comments, historical enrichment and expensive metrics update independently.
- Durable database-first reads for completed sprint data. Missing components import from Jira once per authorized scope, with concurrent requests sharing a job.
- Correct server-capped pagination, stable assignee identity, honest historical completeness and safe refresh.
- Consistent production authentication, configuration, HTTP behavior, database setup, worker supervision, rate limits and observability.
- A migration path that preserves current user/configuration data and encrypted credentials.

Do not add Redis, Memcached, service workers, browser persistent result storage, automatic snapshot TTL refresh, a scheduled freshness service, a new frontend framework, or microservices. In-flight request/job deduplication is execution coordination; it must not become a separate result-cache system. Existing Tableau `maxAge` behavior is outside the requested Jira persistence change and must not be silently changed.

Do not change metric formulas as an incidental performance optimization. Do not claim closed sprints can never change. Do not serve an incomplete import as an empty or complete sprint. Do not run live rule creation or the standalone TCI updater during verification.

## 3. Decision register

### 3.1 Product/deployment choices requested from the user

The user answered all three choices during plan preparation. These answers override the originating review. There are no open product decisions in this plan.

| Decision | Recommended branch described in this package | Alternative and consequence | Status |
| --- | --- | --- | --- |
| U1: production database | SQLite only in development, tests and production. One host, local database file, WAL, short transactions, one supervised worker process. | No PostgreSQL dependencies, code, deployment or migration work is authorized in this plan. | User confirmed: SQLite only |
| U2: stored-data access policy | Revalidate Jira visibility before serving saved reports; fail closed when authorization cannot be established. Data storage and refresh remain database-first. See the strict-access contract and its comment/history limits. | Do not implement an offline/private-archive bypass. | User confirmed: revalidate Jira access |
| U3: metric time semantics | Preserve existing five ScriptRunner categories/formulas and the distinction between sprint-end ticket fields and Jira metric-search points at collection time; label both. | All-historical metric redesign is explicitly deferred. | User confirmed: preserve calculations and label time basis |

The U3 example was a ticket with 5 points at sprint end, later changed to 8. The user chose to preserve the existing calculation behavior and label the different time basis. Correcting truncated data and identity errors may change previously wrong outputs; that is an intended bug fix, not authorization to redesign metric formulas.

### 3.2 Engineering decisions fixed by this plan

| ID | Decision | Reason / implication |
| --- | --- | --- |
| D01 | Keep one modular Flask application and a separate worker process from the same repository. | Existing routing/templates remain; long Jira work stops occupying web threads. |
| D02 | Use a database job table, leases, fencing and idempotent writes. | Required for concurrent tabs, multiple web processes and worker restarts. An in-memory lock is insufficient. |
| D03 | Scope issue-bearing snapshots per portal user, Jira source and access epoch; no cross-user result reuse. | Different PATs can see different issues, comments and histories. |
| D04 | Core tickets, history, comments, five metric categories and final metrics have separate component states. | Failure/retry of one must not discard or refetch another. |
| D05 | Publish complete core tickets after all core pages, rather than stream individual ticket pages in release 1. | Clear completeness, simpler stable grouping, bounded scope. UI shows real page progress during the cold import. |
| D06 | Render current ticket fields provisionally while sprint-end history is unresolved. | Keep tickets usable without claiming current assignees/points are historical. Allow regrouping after history completion. |
| D07 | Preserve full-report export, with explicit completeness gate. | All ticket rows and all five metric categories must be complete. Terminal unavailable history/comment fields may be included only as explicitly unavailable or labeled current fallback, never fabricated zeroes; see the export contract. |
| D08 | Store fetched timestamps, calculation/query/schema versions and immutable component revisions now. | Later freshness can reuse the pipeline; no age-based re-import now. |
| D09 | Existing Refresh Sprints refreshes the sprint catalog only. | Do not turn it into a surprise full-report Jira refresh. Add operator-only explicit snapshot rebuild CLI. |
| D10 | Preserve existing legacy URLs and canonical endpoint names. | Compatibility wrappers delegate to the same authorization and service logic. |
| D11 | Keep existing four migration files unchanged; use a tested frozen baseline bootstrap. | The first historical migration assumes missing tables already exist. See M02; do not blindly stamp arbitrary schemas. |
| D12 | Remove login CSRF recovery-by-bypass, even though one existing test expects it. | Fresh form/token and user resubmission replace unsafe acceptance. |
| D13 | Retry only proven read-safe operations; never automatically retry ambiguous rule creation at any layer. | Transport retries plus route fallbacks currently multiply mutation attempts. |
| D14 | Use Python 3.12, vanilla ES modules through the existing JS entry file, pytest and Playwright. | No application JS build pipeline required. Browser test tooling can remain development-only. |
| D15 | Treat Jira DC/ScriptRunner capability support as a release gate based on actual deployed responses. | Do not assume Cloud endpoints, changelog pagination support, key formats or ScriptRunner query availability. |
| D16 | Retain existing closed-sprint selection and current/previous-year filter for newly imported catalogs. | Persist the import filter/year basis; normal DB reads do not evict reports just because the year changed. |
| D17 | Keep successful snapshot generations until explicit operator purge; no automated successful-data purge. | Cleanup may remove expired operational leases/rate buckets/failed staging only. Deleting a user/project/board must revoke access immediately. |
| D18 | Complete one milestone with working code and tests before broadening changes. | Avoid moving every feature and changing behavior in one unreviewable patch. |
| D19 | SQLite is the sole database implementation. | Use a local persistent disk, WAL, `foreign_keys=ON`, bounded `busy_timeout`, short `BEGIN IMMEDIATE` write transactions, and conditional fenced updates. Never use `FOR UPDATE`, `SKIP LOCKED`, PostgreSQL-specific types or multi-host file sharing. |
| D20 | One supervised worker process, with one core/access lane and two enrichment lanes. | Bounded parallel network work remains possible; DB writes serialize briefly. A database leader lease fences accidental duplicate worker launches. |

## 4. Finding-to-delivery coverage

Use these IDs in tests and the implementation ledger. Every row must end with code references and test evidence.

| ID | Priority | Original finding / affected scope | Milestone | Mandatory validation IDs |
| --- | --- | --- | --- | --- |
| SV01 | P1 | Page locked until metrics finish | M01, M07 | UI01–UI05 |
| SV02 | P1 | Sequential comment hydration blocks tickets | M03, M05–M07 | J06, W05, UI01 |
| SV03 | P1 | No durable issue/metric storage | M04–M06 | DB01–DB06, API01–API04 |
| SV04 | P1 | Premature pagination completion | M01, M03 | J01–J05 |
| SV05 | P1 | Current/history/comment identity mismatch | M03, M05 | I01–I06 |
| SV06 | P1 | Null and incomplete historical reconstruction | M03, M05 | H01–H07 |
| SV07 | P1 | Five searches repeated, request-local fanout | M03–M06 | W01–W09, MET01–MET05 |
| SV08 | P1 | Missing board/sprint relationship validation | M01, M04, M06 | SEC06–SEC10 |
| SV09 | P1 | Refresh deletes before Jira fetch succeeds | M01, M04–M06 | DB05, DB07, API05 |
| SV10 | P2 | Per-issue service/session construction | M01, M03, M08 | HTTP04, PERF01 |
| SV11 | P2 | Lost HTTP configuration in metric threads | M01, M03 | HTTP01–HTTP03 |
| SV12 | P2 | Extra ORM queries and eager DOM work | M07–M08 | PERF02–PERF04, UI06 |
| PR01 | P1 | Weak production configuration defaults | M02, M09 | SEC01, OPS01 |
| PR02 | P1 | Login CSRF bypass | M01–M02 | SEC02–SEC03 |
| PR03 | P1 | Broken empty-database migration path | M02, M04, M09 | MIG01–MIG07 |
| PR04 | P1 | Unsafe HTTP mutation retries | M01–M03 | HTTP05–HTTP08 |
| PR05 | P2 | Disabled account/session/credential revocation | M02, M04–M06 | SEC04–SEC05, SEC11 |
| PR06 | P2 | Missing documented production process model | M09 | OPS02–OPS05 |
| PR07 | P2 | Unpinned dependencies and no reproducible CI | M00, M09 | OPS06–OPS07 |
| PR08 | P2 | Incomplete timings, limits, health and recovery | M03–M04, M09 | OBS01–OBS04, OPS03–OPS08 |

Related scope discovered while preparing this plan, included rather than left behind:

- `JiraProjectsService.list_boards_for_project` and `list_projects_for_board` also advance by requested size and can stop early. Tableau custom-view lookup assumes requested page size. Apply endpoint-specific pagination fixes in M03.
- `RuleCopier` duplicates the per-project board-query pattern and has both project-identifier and actor fallbacks after broad exceptions. Fix them in M01/M03/M08.
- `ProfileService` deletes board/project sprint rows; PAT updates live in `app/blueprints/config/routes.py`; administrative user changes use a SQLite-only script. Wire these into snapshot/job/access invalidation in M04/M08.
- The shared HTTP client accepts absolute URLs and the TCI links service follows Jira `self` URLs with a PAT. Add source-origin/context-path validation and redirect control as part of shared transport hardening; do not send credentials to arbitrary origins.
- `client_log` is unauthenticated with only a Content-Length check. Apply actual body bounds and a separate rate limit while preserving pre-login diagnostic logging.

## 5. Target ownership and file inventory

```text
app/
  __init__.py                         # create_app(config), blueprint/model registration
  config.py                          # explicit environment profiles and bounded settings
  extensions.py                      # shared SQLAlchemy, login, CSRF, migrations
  models.py                          # existing model compatibility exports
  core/
    api.py                           # success/accepted/error contracts
    config_validation.py             # startup fail-closed production checks
    dependencies.py                  # request-local services and immutable worker config
    http_client.py                   # bounded attempts, URL policy, session lifecycle
    security.py                      # active user/session epoch and authorization helpers
    rate_limits.py                   # database-backed atomic counters
    commands.py                      # safe database/admin/operator commands
    health.py                        # liveness/readiness
    jobs/                            # model, repository, worker loop, leased Jira slots
  integrations/
    jira/
      client.py                      # Jira-specific adapter and typed errors
      pagination.py                  # offset pagination contracts
      capabilities.py                # configured/verified Jira DC capability manifest
      identity.py                    # canonical identities and verified aliases
      access.py                      # U2 policy adapter
    tableau/                         # only shared transport/pagination adaptations initially
  features/
    automation/sprint_viewer/
      routes.py                      # thin validated/authenticated API mapping
      schemas.py                     # exact input/response dataclasses and serializers
      models.py                      # scoped series, generations and component rows
      repository.py                  # no unscoped snapshot lookups
      service.py                     # get/create snapshot and orchestrate components
      calculations.py                # pure, versioned quality and scrum calculations
      history.py                     # historical reconstruction, no Flask context
      jobs.py                        # catalog/core/history/comments/metrics handlers
    automation/rule_copier/           # retain workflow, repair safe mutation handling
    settings/integrations/            # move integration handlers here in M08
    settings/projects_boards/         # explicit eager loading + revocation hooks
    settings/tableau_custom_views/    # retain forms/routes and update transport lifecycle
    reports/tci/                     # retain behavior and update transport lifecycle
  services/                          # compatibility re-exports while consumers migrate
  blueprints/                        # compatibility URL/auth wrappers retained
  templates/                         # same paths and visual structure
  static/js/
    sprint_viewer.js                  # stable entry; dynamically import feature module
    sprint_viewer/{index,api,state,render,export}.js
workers/
  sprint_import_worker.py             # python -m workers.sprint_import_worker
scripts/
  smoke_check.py
  benchmark_sprint_viewer.py
  jira_capability_probe.py            # explicit read-only staging diagnostic
requirements/
  runtime.in
  runtime-py312-windows.lock
  runtime-py312-linux.lock
  dev.in
  dev-py312-windows.lock
  dev-py312-linux.lock
deploy/
  production.env.example
  waitress.md
  linux/                             # systemd units and proxy example
  windows/                           # service setup/runbook, hidden noninteractive process
tests/
  conftest.py
  fixtures/{jira,tableau,migrations}/
  unit/{sprint_viewer,core}/
  integration/{sprint_viewer,migrations,security}/
  browser/
  performance/
```

Do not move unrelated working modules just to match the diagram. Complete the specified ownership boundaries, and leave documented wrappers rather than duplicate implementations. Do not create generic base repository/service hierarchies. Model registration must happen before migration autogeneration. Keep existing imports working until their consumers/tests have moved intentionally.

## 6. Execution milestones

### M00 — Baseline and executable ledger

Dependencies: none. No production changes.

1. Read all package documents and applicable `AGENTS.md`. Check current Git state; the reviewed workspace had no `.git`. Do not invent a branch or claim commits exist. If operating in a Git checkout, preserve pre-existing changes and record base revision.
2. Record Python/dependency versions, route map, existing tests and current migration head. Never read secrets into the transcript or run production migrations to gather a baseline.
3. Run `python -m pytest -q`; the prior baseline was 69 passing tests, not a permanent expected count. Run the smoke script with explicit isolated test configuration after adapting its current environment dependence.
4. Capture UI baseline screenshots for Sprint Viewer states and other affected pages using synthetic data. Capture representative current metric fixtures from the existing calculation code and the known synthetic bugs.
5. Update the initialized `docs/implementation/production-hardening/implementation-status.md` with each coverage ID, milestone state, code links, tests/results, unresolved deployment facts and next action. Preserve prior evidence and update only completed work as work proceeds.
6. Separate dependency manifests early; generate lock files from the verified baseline, add new dependencies only in the milestone that needs them. Do not blindly upgrade the whole stack while diagnosing behavior.

Exit: reproducible baseline, no production state touched, tracking ledger created.

### M01 — Correct immediate P1 behavior before architecture changes

Dependencies: M00. Expected existing files: Sprint Viewer JS/routes/service; auth routes; Rule Copier routes/service; core HTTP/dependencies; relevant tests.

1. Split issue and metric completion in the existing JS handler. Keep the request generation guard; end page locking after issue success/failure, regardless of metrics. Handle the metric promise rejection even when issues fail; stale metric completion cannot re-enable controls on a newer request. This is the bridge fix, replaced by the durable state machine in M07.
2. Construct one Sprint Viewer service in the issue handler, not N + 6 instances. Keep calculations static/pure where possible.
3. Fix Jira pagination termination/progress and deduplication before persisting any new data. Add the capped-page regression before the change. Apply the full shared adapter in M03.
4. Require positive integer board/sprint IDs (reject booleans, floats, empty strings and overflow). Validate saved board/project scope and an actual board/sprint association before contacting `/sprint/{id}/issue`. A missing association must not succeed with blank metadata.
5. On sprint catalog refresh, fetch completely before writing; transactionally reconcile/upsert/remove rows only after success. Preserve old rows on error. Resolve concurrent first-load uniqueness conflicts by rereading successful data rather than returning generic 500.
6. Remove `LoginForm(meta={"csrf": False})` login fallback. Return HTTP 400 and a fresh unbound login form, retain a non-sensitive identifier if desired, never echo the password. Valid resubmission succeeds normally. Update the unsafe existing stale-CSRF expectation, not the security requirement.
7. Restrict transport mutation retries and both Rule Copier fallback layers. Preserve status/error classification through service exceptions. Known, documented non-mutating rejection may permit an appropriate alternate actor/identifier; timeout, 5xx, parse failure after success, or unclassified exception may not. See backend mutation contract.
8. Inject resolved HTTP retry/timeout configuration into executor work, never rely on `current_app` inside a thread. Keep the old parallel method callable until M06 removes it from web requests.

Exit: original bad scenarios are covered by tests that fail against the old behavior; completed tickets remain interactive during delayed metrics. No snapshot schema is required yet.

### M02 — Production security and safe database entry points

Dependencies: M01. Use the user's SQLite-only decision throughout.

1. Implement `APP_ENV=development|test|production`, explicitly selected in the app factory/config loading. `FLASK_ENV` must not be relied on as environment enforcement. Test configs stay explicit; tests must not inherit real production secrets or DB URLs.
2. Production startup validates a non-placeholder signing secret of at least 32 random bytes, a valid Fernet key, enabled integration HTTPS URLs without userinfo/query/fragment, approved host configuration, secure cookies, disabled debug, and bounded worker/HTTP/DB settings. Do not print rejected secret values. Optional disabled integrations need not prevent unrelated features starting; expose their unavailable state cleanly.
3. Add active/deleted checks and a session epoch to every authenticated request. Harden `load_user` against malformed IDs. Password changes and account disable/delete revoke sessions; PAT changes revoke credential/access epochs and Jira validation grants. Preserve the explicit absolute timeout and explicit Extend Session behavior; polling must never extend it.
4. Make API unauthenticated/expired responses JSON 401, including canonical and legacy APIs. HTML navigation still redirects to canonical login. CSRF errors are JSON 400 for APIs and appropriate form responses for HTML. Test hook/decorator order.
5. Add safe DB CLI: `flask --app wsgi:app setup-db --check` and `setup-db --apply`; see section 7. Do not use current ORM `create_all()` followed by historical migrations.
6. Add baseline metadata frozen at `9c2a1f7b6d10`, in a versioned bootstrap module independent of live ORM classes. Test columns/constraints/indexes against the reviewed legacy head.
7. Create production-safe account administration commands using the ORM and shared security services. Adapt `manage_users_sqlite.py` into a compatibility wrapper for supported mutations; its raw SQL editing path must not bypass epoch updates, schema checks or invalidation.

Exit: SEC01–SEC05 and legacy migration tests pass. New production checks never silently select development mode to make tests/deployment work.

### M03 — Shared Jira/Tableau transport, pagination and pure calculations

Dependencies: M01–M02.

1. Implement the exact transport policies, ownership and deadline interface in backend contracts. Apply to `JiraService`, `JiraProjectsService`, `JiraIssueLinksService`, `RuleCopierService`, `SprintViewerService`, and `TableauService`; update injection fakes rather than hardcoding new factories around them.
2. Implement Jira offset pagination and Tableau page-number pagination separately. Replace all affected loops. Fix Settings project/board listing as well as Sprint Viewer. Preserve the Tableau server's existing unsupported-ID-filter workaround.
3. Enforce URL origin/base-path policy for absolute `self` URLs and redirects. Configure enterprise CA/proxy support without `verify=False`. URL policy must accommodate a Jira context path such as `/jira`.
4. Move field extraction, canonical identity mapping, historical reconstruction and formulas into pure modules. Stop retaining comment bodies/full raw unrelated Jira fields. Use finite numeric parsing; preserve unestimated nulls and current round-to-two-decimal output compatibility.
5. Add exact capability handling for Jira DC history, principal lookup and ScriptRunner. Unsupported history becomes an explicit unavailable component, not a fabricated completed result.
6. Record timings and classifications for successful and failed upstream attempts without logging PATs, JQL literals with private identifiers, comments, response bodies or query secrets by default.
7. Audit the standalone `app/services/test_tci.py` script only for shared transport boundary/accidental runtime inclusion; move it to an explicitly named operator-script location with its existing dry-run behavior if needed. Do not execute it against Jira, change team business rules, or introduce automatic retries for its writes.

Exit: J/I/H/MET/HTTP unit cases pass; existing Tableau/Rule Copier workflows remain compatible under fakes. No live performance claim.

### M04 — Persistence, access epochs, job primitives and rate limits

Dependencies: M02–M03; SQLite and live access revalidation are fixed requirements.

1. Add forward migrations after legacy head for sources, scope epochs, catalogs, snapshot series/generations, component revisions/items, principal aliases, jobs, leased Jira slots, operation records and rate-limit buckets. Exact required columns and uniqueness appear in backend contracts.
2. Implement only scoped repository methods: callers pass the authenticated scope, never user ID from JSON. Enforce ownership for ID lookups before serializing any counts, timestamps, progress, errors or exports.
3. Implement atomic get/create of a snapshot series and candidate generation; completed empty snapshots are hits. Allocate generations in a short SQLite `BEGIN IMMEDIATE` transaction; reread uniqueness conflicts. Version tuple participates in compatibility checks.
4. Implement worker leadership, job claiming, heartbeat, fencing, expiry recovery and transactional component publication. Test against a real file-backed WAL SQLite database with distinct connections and processes. In-memory tests cannot substitute for locking/restart tests.
5. Wire PAT update, password/account change, project/board deletion and Jira source change to immediate access invalidation and job fencing. Account/credential changes must be checked before every new upstream batch and at publish time.
6. Implement DB rate buckets and leased Jira slots. Do not hold a transaction open while waiting for Jira or during backoff. See exact limits and priority rules below.
7. Preserve legacy sprint rows as unverified metadata during migration. Do not mark them a complete catalog: legacy pagination could have truncated them and empty catalogs have no completion sentinel. One verified catalog import populates the new complete catalog on first use.

Exit: MIG/DB/W/SEC ownership and concurrency tests pass on file-backed SQLite. Secret data never appears in jobs or serialized progress.

### M05 — Durable import pipeline

Dependencies: M04.

1. Worker imports catalog then core ticket pages without full comment/history hydration. Core rows are staged by component revision and published only at verified end of pagination.
2. Core publication enqueues history and the five metric categories transactionally with unique active-job keys. Comments can fetch concurrently at lower priority; the relevant-comment calculation waits for canonical history/team identity or reports unavailable.
3. Import metric membership and point values for every category, including removed-scope issues absent from core. Store category inputs before aggregating. Reuse completed categories on retry.
4. Reconstruct historical fields against sprint `complete_date`; current fields remain separately stored. Respect unavailable/truncated history. Do not overwrite provisional fields in place without a new response revision.
5. Final calculation job is runnable only when its required categories are complete. It performs no Jira I/O. Dependent card values can publish earlier once all their category dependencies are complete.
6. Implement progress from real work units: pages received/expected, issues enriched/expected, category state. Unknown totals are unknown, not a made-up percentage.
7. On worker restart, restart the failed component from offset zero into a fresh staging revision rather than blindly resume an unstable offset. Already published components stay intact. This deliberate restart trades some failed-run work for correctness.
8. Keep successful generations indefinitely. Explicit operator `rebuild-sprint` allocates a candidate and retains the previous active generation until the whole required candidate is complete. Ordinary reads and browser Retry never become full refresh.

Exit: delayed comments/metrics cannot delay published core; crash/retry cannot corrupt or duplicate a snapshot; removed scope and empty components remain correct.

### M06 — Database-first APIs and access enforcement

Dependencies: M05. Apply the user's mandatory Jira access revalidation policy.

1. Implement v2 asynchronous contracts behind `SPRINT_VIEWER_MODE=direct|snapshot` and a per-user rollout list. `direct` is the corrected M01 behavior, not the original unsafe implementation. Production target is `snapshot`.
2. Existing canonical issues/sprints/metrics URLs remain, with additive `202` processing responses in snapshot mode; completed responses retain existing fields and add metadata. Preserve legacy wrappers with identical behavior/deprecation headers. Explicitly document the asynchronous contract change for scripts consuming old endpoints.
3. Add status, components, bounded ticket pages, retry and export-readiness endpoints as specified. Polling is read-only and never implicitly queues additional work; explicit POST starts/retries jobs.
4. In snapshot mode no route invokes the old Jira-heavy metric parallel method or comment hydration loop. Old `total_sp`/`total_count` client inputs may be accepted for compatibility, but are ignored for authoritative results.
5. Apply U2 on status/data/export, not merely on the first POST. No cached result is returned before access verification permits it. Fail closed on revoked scope. Distinguish unavailable upstream authorization from a missing snapshot.
6. Strict-access policy must account for all issue IDs from core and metric memberships, including removed items, and sensitive comment/history fields; `/myself` or project permission alone is insufficient. See backend U2 contract for reduced-detail handling when field-level verification cannot be guaranteed.
7. Ensure input shape validation, sanitized error contracts, bounded pagination and request limits across related APIs; do not let JSON scalars/lists trigger unhandled `.get()` errors.

Exit: DB-hit data-call counts and cross-user/board/sprint/epoch tests pass. Direct-mode and snapshot-mode route tests cover canonical and compatibility surfaces.

### M07 — Independent UI states and complete export

Dependencies: M06. Follow frontend contract exactly.

1. Introduce ES modules without changing the stable feature script path or loading it twice. Keep DOM IDs, classes, visual layout and normal user actions.
2. Replace global lock state with independent catalog/core/history/comments/metrics/export states and generation-bound AbortControllers.
3. Render core groups first, initially marked as current/provisional when appropriate. Update historical grouping without losing expanded state where identity remains the same; avoid forced scroll jumps.
4. Lazy-create collapsed group rows in chunks, retain full data separately from DOM and use stable issue/principal IDs. Fix scope stars for both already-rendered and newly-expanded rows.
5. Implement one status poll loop per active generation with backoff/jitter and request cancellation. Clear timers on reset, navigation, session expiry and terminal completion. Metric failure presents inline retry and preserves tickets.
6. Full XLSX export reads one authorized coherent generation/revision. Export from data, never the rendered subset. Preserve columns, formulas/labels and file naming; include source/fetch/time-basis metadata. Escape XML, encode string cells as strings, and test formula-like Jira summaries.
7. Run real browser tests with delayed/mock APIs and visual comparisons for Sprint Viewer plus shared session/login/navigation changes.

Exit: UI/EXP tests pass; tickets respond while enrichment is slow or fails; no duplicate jobs from repeated clicks/tabs; no stale callbacks touching a newer selection.

### M08 — Complete project-wide adoption and revoke paths

Dependencies: M03–M07.

1. Remove relationship-level select-in loading from authentication hot paths; use explicit `selectinload(UserProject.boards)` in views that need it. Replace both Sprint Viewer and Rule Copier query-per-project loops. Measure counts rather than guessing indexes.
2. Move integration settings business handlers into the existing feature package while preserving wrapper names/imports/forms. Keep Tableau sign-in/sign-out and token ownership behavior; close clients after sign-out even on exceptions.
3. Use the shared credential/admin services for user changes. Preserve `User` public model imports, password hashing and encrypted bytes. Add secure SQLite disable/revoke commands and route the existing administration script through them.
4. Project/board delete must invalidate all matching snapshot scopes/jobs in the same transaction. A board can appear under more than one saved project: revoking on deletion is conservative; adding it back allocates a new scope epoch and must not resurrect old snapshots automatically.
5. Keep all current canonical/legacy URLs, form exports, TCI preview logic and settings flows. Update structural tests to reflect ownership contracts rather than insisting implementation text remain in old files.
6. Document any retained compatibility wrapper and its callers. Do not remove legacy routes as part of this performance release.

Exit: all existing functional workflows pass on SQLite; query count is independent of the number of projects for board-list page loads; disabling an account revokes already-open sessions.

### M09 — Production deployment, measurement and release readiness

Dependencies: all previous milestones and user decisions.

1. Add locked runtime/dev requirements and reproducible CI. Runtime addition: Waitress for the selected deployment; use Python's SQLite support, no PostgreSQL driver, Celery or Redis. Dev dependencies include pytest, Python Playwright/pytest-playwright, openpyxl (export validation), pip-tools (lock generation) and pip-audit. Generate and test separate Windows/Linux Python3.12 hash locks; platform-specific transitive dependencies must not be lost. Keep root `requirements.txt` as a documented compatibility manifest or installer entry, with production instructions explicitly using the platform runtime lock and `--require-hashes`.
2. Add `health/live`, web readiness, worker heartbeat/readiness, bounded structured observations, request/rate/payload limits, trusted proxy/host configuration and security headers.
3. Produce deploy examples for the actual host. Default portable WSGI choice: Waitress behind a TLS reverse proxy, with a separate supervised worker. Linux systemd and Windows service-manager instructions must be explicit about working directory, venv executable, service account, restart and shutdown. Do not silently install a Windows service manager.
4. Use an expand-first migration rollout, worker capability/schema checks and targeted feature activation. Record old deployment/artifact/config for rollback. Rehearse SQLite backup/restore and file-backed concurrent operation; no database-engine switch.
5. Run load scenarios and failure drills from the validation document. Record median/p95, Jira attempts, duplicate job counts, queue delay, DB time and client readiness. Do not substitute unit-test time for end-user performance.
6. Update `readme.md`, `docs/architecture.md`, `docs/routes.md`, `docs/first_time_setup.md`, `docs/env_reference.md`, `docs/operations.md`, `.env.example` and the implementation ledger. Remove the old instruction prohibiting issue persistence without automatic freshness; the user explicitly authorized durable static snapshots.
7. Audit dependencies with their locked manifest against the approved vulnerability source. Triage findings individually; report real failures rather than suppressing the check or claiming an unperformed security audit.

Exit: all coverage rows have implementation and passing evidence; integration/browser/SQLite concurrency/migration gates have run; deployment-specific acceptance is either completed or explicitly reported as a release blocker, not a silently skipped success.

## 7. Database bootstrap and conversion runbook to implement

Historical chain: `c3d00bc3ae67 -> f8954404f3b1 -> 44a4a3ce3141 -> 9c2a1f7b6d10`. The first file alters an existing table. Do not change these applied files' contents/revisions or add `create_all()` to application startup.

Implement `setup-db --check` as read-only schema/revision inspection. Implement `--apply` using the following cases, emitting no credential values:

| Database state | Required action |
| --- | --- |
| Empty database | Under an exclusive migration operation, create frozen schema matching legacy head `9c2a1f7b6d10`, verify it, stamp exactly that legacy revision, then apply new forward migrations. Frozen metadata must not import current models. |
| Versioned at known old revision | Apply remaining historical then new migrations. Verify prerequisite baseline tables; abort if the recorded revision lies about the schema. |
| Versioned at known current revision | Apply only pending forward migrations; repeated invocation is a no-op. |
| Unversioned but exact legacy-head schema | `--check` identifies it. Require explicit `--adopt-legacy-head` with backup reference for stamp-then-upgrade; compare all required tables/columns/types/nullability/uniques/indexes/FKs first. |
| Unversioned/partial/unknown schema | Stop with a schema-diff report. Never stamp latest, delete tables, or assume a duplicate column means everything is already migrated. |

Change `flask init-db` into a deprecated wrapper around the safe bootstrap or reject it with the new command; do not keep a second unversioned path. Direct `flask db upgrade` against an empty DB should fail early with an actionable bootstrap instruction rather than a cryptic missing-table stack trace. The supported documented first-time command is `setup-db --apply`; established databases may use ordinary `db upgrade`.

New migration order: security epoch additions; source/scope/catalog/snapshot/component schema; jobs/slots/limiter/operation records; indexes/backfills. Use defaults/backfill first, then non-null constraints. Avoid table renames or destructive drops in this release. Use Alembic SQLite batch operations only where necessary, with a pre-migration backup and post-migration FK checks. No automatic production downgrade removes stored snapshots.

SQLite deployment and recovery:

1. Resolve the SQLite file to an explicit absolute path on a local persistent disk shared by the web and worker on the same host. Refuse in-memory production URLs and document that SMB/NFS/synchronized folders are unsupported.
2. Take a backup with SQLite's online backup API; a raw copy of only the main file while WAL writes are active is not a valid backup strategy. Verify the backup using `PRAGMA integrity_check` and `foreign_key_check` against the backup file.
3. During schema migration, stop worker claiming and web writes, drain requests, record the current revision, and apply the safe bootstrap/upgrade against the intended file. Preserve IDs, nulls, password hashes and encrypted PAT bytes.
4. Set WAL once in a controlled initialization connection; verify it on startup. Set `foreign_keys=ON`, `busy_timeout=5000`, and `synchronous=FULL` on each connection. Use a bounded SQLite connection pool or NullPool chosen explicitly in the backend contract, and never share sessions across threads.
5. After migration verify revision, table/row counts where relevant, FK integrity and startup/read-only smoke tests. Start the supervised worker and enable writes.
6. Restore drills use a different absolute local file path and no live Jira calls. Validate the same Fernet key remains available without printing or rewriting tokens.
7. Restore a backup into production only with stopped processes and a recorded rollback decision; replace the correct main/WAL/SHM set safely using SQLite-aware instructions. Writes after the backup can be lost; record that consequence instead of claiming lossless rollback.

## 8. Configuration to implement

The values below are initial engineering defaults, configurable and validated. They are not capacity guarantees. Existing names retain compatibility mappings for one release; conflicts produce a clear startup error or documented precedence, not hidden fallback.

| Setting | Initial value / rule |
| --- | --- |
| `APP_ENV` | Explicit `development`, `test` or `production`; production manifests set production. |
| `SPRINT_VIEWER_MODE` | `direct` during staged rollout; `snapshot` production target. |
| `SPRINT_VIEWER_SNAPSHOT_USER_IDS` | Empty means no allowlist restriction when mode=snapshot; explicit list allows targeted rollout. Never accept from a request. |
| `SPRINT_SNAPSHOT_ACCESS_POLICY` | `jira_revalidate` only for this release; reject offline/unknown values. |
| `JIRA_SOURCE_ID` | Operator-provided stable deployment key; source URL/config changes require new source identity. |
| `JIRA_STORY_POINTS_FIELD`, `JIRA_APPLICATION_FIELD`, `JIRA_EPIC_LINK_FIELD` | `customfield_10106`, `customfield_11700`, `customfield_10100`; validate format and capture in query version. |
| `HTTP_CONNECT_TIMEOUT_SECONDS` | 5; positive bounded range. |
| `HTTP_READ_TIMEOUT_SECONDS` | 20; maps from existing external timeout if new value absent. |
| `HTTP_OPERATION_BUDGET_SECONDS` | 60 per HTTP operation including bounded reads/attempts/backoff. Not a whole multi-page sprint deadline. |
| `EXTERNAL_HTTP_RETRY_TOTAL` | 2 read-safe retries (3 attempts maximum); capture existing value explicitly during upgrade rather than silently change operations. |
| `HTTP_RETRY_AFTER_MAX_SECONDS` | 30; if upstream asks for longer, yield/defer the job instead of sleeping a web thread. |
| `HTTP_MAX_JSON_BYTES` | 16 MiB; oversized responses fail explicitly. |
| `TABLEAU_MAX_CSV_BYTES` | 32 MiB; enforce while streaming, before unbounded allocation. |
| `JIRA_REQUESTED_PAGE_SIZE` | 50 core/catalog; metrics 200; server returned metadata wins. |
| `IMPORT_MAX_PAGES`, `IMPORT_MAX_ISSUES` | 10,000 pages / 100,000 unique issues as hard error bounds; never truncate silently. |
| `JIRA_MAX_INFLIGHT_PER_SOURCE` | 4 app-originated upstream calls across web/worker; at most 2 background calls, leaving 2 available to interactive/core/access work. |
| `SPRINT_WORKER_CONCURRENCY` | 3 lanes: 1 core/access + 2 enrichment; one worker process, no nested executor fanout. |
| `SPRINT_JOB_LEASE_SECONDS`, `SPRINT_JOB_HEARTBEAT_SECONDS` | 120 / 15; fenced heartbeats, DB server time. |
| `SPRINT_JOB_MAX_ATTEMPTS` | 3 total attempts including initial attempt; healthy continuations do not increment this count. |
| `SPRINT_COMPONENT_MAX_RUNTIME_SECONDS` | 1,800 per attempt; exceeding it fails/defer explicitly rather than publishing partial data. |
| `SPRINT_JOB_POLL_SECONDS` | 1 while work is available; idle backs off to 5. |
| `SPRINT_WORKER_STALE_SECONDS` | 60 for heartbeat readiness; independent process heartbeat continues during long jobs. |
| `SQLITE_BUSY_TIMEOUT_MS`, `SQLITE_WRITE_BUDGET_SECONDS` | 5,000 / 5 per write transaction; fail/defer on contention without unbounded nested retry. |
| `SQLITE_CONNECTION_POOL` | SQLAlchemy NullPool for file-backed DB; short-lived per-unit connections with configured PRAGMAs. Tests use their own explicit in-memory configuration when needed. |
| `MAX_CONTENT_LENGTH` | 2 MiB globally; client-log 8 KiB; ordinary JSON control APIs 64 KiB. Rule payload uses global limit. |
| `WEB_THREADS` | 8 initial Waitress threads; benchmark, do not multiply Jira slots when adding web processes. |
| `TRUSTED_HOSTS`, trusted proxy count/address | Required for production manifests; never trust arbitrary forwarded headers. |
| `JIRA_ENABLED`, `TABLEAU_ENABLED` | Explicit feature flags; missing config for an enabled integration is fatal in production. |

Preserve existing session timeout, secure cookie defaults, source-specific Tableau settings, trace toggles and canonical deprecation headers. Keep current logging request correlation; production defaults to INFO, tracing off.

Initial limits: login 10 attempts per normalized identifier per 15 minutes plus 30 per trusted IP per 15 minutes; signup/PAT validation 10 per user-or-IP per 15 minutes; new sprint import requests 10/minute/user, max 3 active snapshot generations/user; explicit retries 5/minute/user; polling 120/minute/user; Rule Copier creates 5/minute/user; client-log 30/minute per session-or-IP. Count unique new jobs for import quotas, not deduplicated retries/status reads. Alias routes share the same logical bucket. Responses use 429 + Retry-After; account existence must not be disclosed. Tune after measured use, keep limits enforced across processes through the DB.

## 9. Release and rollback

Use a maintenance window for SQLite schema migration. Deploy additive schema, then corrected direct-mode web, the single supervised worker, and snapshot-capable UI/API together. Check worker/schema/WAL readiness before enabling the feature for selected users. Do not launch migrations automatically in every WSGI/worker process.

Require: U1/U2/U3 recorded; baseline backup restored successfully in a rehearsal; actual Jira capability manifest; real file-backed SQLite concurrency/migration tests; full functional/browser checks; no new secret exposure; and cold/warm/stress results with request-count evidence.

If snapshot mode has a regression, disable new import admission and switch the affected users to corrected direct mode only if safe for upstream capacity. Stop worker claiming gracefully, retain snapshots/jobs for diagnosis, and deploy a forward fix. Do not restore the original CSRF bypass, unsafe retries, or broken pagination in rollback. Data schema stays expanded. A destructive database rollback is a separate operator decision with a verified backup and write reconciliation.

Default operational backup policy to implement: daily SQLite online backup into an encrypted, access-restricted backup volume/service, retained14 days, plus a pre-migration backup; run a restore drill before release. Use existing OS/infrastructure encryption (for example the organization's encrypted Windows backup volume), not a custom cryptographic archive format or reuse of the Jira PAT Fernet key. Require an operator-configured absolute backup directory and record verified encryption/ACL coverage as a deployment gate. State the actual RPO (up to24 hours) honestly. More frequent backup is an operator setting if required; do not introduce PostgreSQL/WAL-archiving/PITR machinery. Keep PAT/session encryption keys in the deployment secret store and back them up under a separate controlled recovery procedure. Backup scheduling is operational protection, not the deferred Jira freshness scheduler.

## 10. External references and what they justify

- SQLite WAL supports concurrent readers with a writer, while writes still serialize. Use short transactions and local-file deployment. [SQLite WAL](https://www.sqlite.org/wal.html)
- Flask documents Waitress as a Windows-compatible WSGI deployment option. [Waitress](https://flask.palletsprojects.com/en/stable/deploying/waitress/)
- Flask documents security controls including resource limits and cookie/header practices. [Flask security](https://flask.palletsprojects.com/en/stable/web-security/)
- Alembic documents creating a database and stamping a baseline; this project's frozen-schema validation/adoption rules are stricter application-specific safeguards. [Alembic cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html)

Do not replace validation against the deployed Jira DC/ScriptRunner version with documentation for Jira Cloud.
