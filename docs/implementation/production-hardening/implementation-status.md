# Implementation ledger

Implementation completed on branch `feature/production-hardening-implementation` from base `be48f22`. The software remains SQLite-only, preserves the existing metric formulas with explicit time-basis labels, and revalidates Jira access before saved report data or exports are returned. Automatic age-based freshness remains deferred.

## Decisions

| Decision | Implemented choice |
| --- | --- |
| Database | SQLite only; file-backed WAL for production and explicit in-memory test profiles |
| Saved report access | Live Jira identity, board/sprint, exact core/metric membership, and comment visibility checks before display/export |
| Metric definitions | Existing five ScriptRunner searches and formulas retained; results say `Jira points at collection time` |
| Freshness | No timer, TTL, or scheduler; `rebuild-sprint` is operator-only |
| UI | Existing template, IDs, layout, routes, and direct-mode behavior preserved; snapshot mode is staged by configuration |

## Milestones

| Milestone | Status | Main evidence |
| --- | --- | --- |
| M00 baseline | Complete | Base revision recorded; Python 3.12/SQLite baseline; initial 69 tests; isolated smoke configuration |
| M01 immediate fixes | Complete | Corrected direct-mode UI bridge, strict IDs, atomic sprint reconciliation, CSRF rejection, safe mutation retries |
| M02 security/bootstrap | Complete | Production validation, server sessions/epochs, safe administration, frozen legacy bootstrap and tested repeatable migrations |
| M03 adapters/calculations | Complete | Bounded HTTP client, Jira/Tableau pagination, canonical identities, pure metric calculations, capability probe |
| M04 SQLite persistence/jobs | Complete | Snapshot/revision/job/access/limiter/slot schema, WAL/PRAGMAs, leases/fences/heartbeats, file-backed claim test |
| M05 import pipeline | Complete | Core-first publication; independent history/comments/five metric jobs; immutable revisions and final pure calculation |
| M06 authorized APIs | Complete | DB-first snapshot/status/page/component/retry/authorize/export APIs and legacy wrappers |
| M07 UI/export | Complete | ES module state machine, lazy row chunks, background enrichment, reauthorization, worker-built XLSX |
| M08 project-wide adoption | Complete | Request-local services, hot-path ORM fixes, shared revocation/admin services, retained compatibility wrappers |
| M09 release engineering | Software complete; deployment validation pending | Hash locks, Windows/Linux CI, Waitress/service examples, health checks, smoke/benchmark/audit and operating runbooks |

## Finding coverage

| Finding | Status | Implementation references | Regression evidence |
| --- | --- | --- | --- |
| SV01 UI lock | Fixed | `app/static/js/sprint_viewer.js`, `app/static/js/sprint_viewer/index.js` | `tests/test_sprint_viewer_browser.py` |
| SV02 comment blocking | Fixed | `app/services/sprint_viewer_service.py`, `app/features/automation/sprint_viewer/jobs.py` | browser delayed-metrics test; Sprint Viewer service tests |
| SV03 persistence | Fixed | Sprint models/repository/jobs and migration `b27d5f8a9c02` | snapshot miss/dedup/rebuild tests |
| SV04 pagination | Fixed | `app/integrations/jira/pagination.py`, Jira services, Tableau service | capped/duplicate/empty-page tests |
| SV05 identity | Fixed | `app/integrations/jira/identity.py`, persisted principals/aliases | historical alias, duplicate display-name, comment identity tests |
| SV06 history | Fixed | history component and sprint-end reconstruction | null/zero, empty complete changelog and historical reconstruction tests |
| SV07 repeated metrics/fanout | Fixed | five durable category jobs, final pure calculation, leased source slots | snapshot job/slot tests; metric formula tests |
| SV08 board/sprint scope | Fixed | strict route and repository selection checks | phase 6 route tests and hardening tests |
| SV09 atomic refresh | Fixed | fetch-before-write catalog reconciliation and verified empty catalog marker | route failure tests; migration/catalog schema coverage |
| SV10 service/session reuse | Fixed | `app/core/dependencies.py` request memoization and teardown | structural adoption suite; CPU benchmark |
| SV11 worker HTTP config | Fixed | shared configured HTTP client; no metric executor | HTTP policy tests |
| SV12 DB/DOM work | Fixed | explicit `selectinload`, lazy 50-row rendering, stable IDs | browser test and project route suite |
| PR01 production config | Fixed | `app/core/config_validation.py`, production manifest | configuration tests and startup smoke |
| PR02 CSRF | Fixed | auth CSRF handler; no fallback submission | session/navigation tests |
| PR03 database bootstrap | Fixed | `setup-db`, frozen legacy schema, additive migrations | empty/repeat/backup/integrity test |
| PR04 mutation retries | Fixed | one retry layer, POST one attempt, Rule Copier operation records | HTTP and Rule Copier fallback tests |
| PR05 revocation | Fixed | auth sessions and session/credential/access epochs | snapshot cancellation and session tests |
| PR06 process deployment | Fixed | `deploy/` Waitress, systemd, Windows supervisor guidance | compile/smoke; deployment execution is environment-specific |
| PR07 dependency/CI | Fixed | four Python 3.12 hash locks and two-platform GitHub Actions | local `--require-hashes --dry-run`; pip-audit clean |
| PR08 operations/limits | Fixed | health, rate buckets, payload bounds, worker commands/runbooks | API, worker fence, smoke and benchmark evidence |

## Verification runs

Local Windows verification on 2026-09-09 with Python 3.12.14 and SQLite 3.53.1:

- `python -m compileall -q app workers migrations scripts`: passed.
- `python -m pytest -q --tb=short --disable-warnings`: **84 passed**; two non-failing dependency warnings.
- Real Chromium/Flask browser test: passed. It proves tickets become interactive while metrics remain pending and validates formula-like Jira summaries remain XLSX string cells.
- Empty file-backed database bootstrap, repeated apply, SQLite online backup, integrity check, foreign-key check, and migration head verification: passed.
- Distinct-thread, file-backed WAL job claim race: exactly one consumer acquired the fenced job.
- `python scripts/smoke_check.py`: `SMOKE_OK`.
- Synthetic CPU transformation benchmark, 30 runs: 50 tickets median/p95 0.131/0.148 ms; 250 tickets 0.507/0.527 ms; 1,000 tickets 1.978/3.589 ms. These are local transform costs, not end-user or Jira latency claims.
- Runtime Windows hash lock `pip install --dry-run --require-hashes`: passed.
- Runtime dependency audit: `No known vulnerabilities found`.

## Deployment gates still to record

These facts require the target environment and are intentionally not guessed by the implementation:

- Jira Data Center and ScriptRunner versions/capabilities, actual page caps, principal shapes, history completeness, and issue/comment visibility behavior using `scripts/jira_capability_probe.py`.
- Representative cold import, DB-hit authorization, queue-delay, duplicate-job, and browser-ready median/p95 timings under expected concurrent use.
- Absolute production SQLite path on local persistent storage, service account ACLs, reverse-proxy topology, trusted hosts, CA/proxy settings, and Windows/Linux supervisor choice.
- Encrypted backup destination, approved daily retention, and a restored-backup rehearsal using the production Fernet key without live Jira calls.
- Linux CI execution is defined in `.github/workflows/ci.yml`; its result is recorded by the remote CI run after push.

## Deviations and clarifications

- A before-change visual screenshot baseline was unavailable in the local planning artifact. The implementation kept the existing template/layout and added a real browser behavior test; deployment visual review remains a release gate.
- Linux and Windows lock files resolve the same current dependency graph and contain package hashes. Windows was validated locally; Ubuntu is validated by the CI matrix with Chromium installation.
- History is withheld unless `JIRA_HISTORY_VISIBILITY_FOLLOWS_ISSUE` is explicitly enabled after the Jira capability probe supports that policy. This fails closed rather than exposing saved history on an unsupported permission assumption.
