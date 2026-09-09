# GPT Sol handoff

Use the prompt below to start implementation in the Scrum Portal workspace. It authorizes implementation of the documented fixes; it does not imply the implementation already exists.

## Copy/paste prompt

```text
Implement the Scrum Portal P1/P2 remediation plan in this repository.

First read, in order:
1. docs/implementation/production-hardening/README.md
2. docs/implementation/production-hardening/backend-contracts.md
3. docs/implementation/production-hardening/frontend-and-validation.md
4. docs/implementation/production-hardening/implementation-status.md

The earlier evidence is in docs/sprint-viewer-performance-review.md.
The implementation package supersedes its tentative architecture suggestions.

All three user decisions are final:
- SQLite only, including production. Do not implement PostgreSQL, its driver,
  its migrations, or its deployment. Use the documented local-file WAL,
  short-transaction and single-worker SQLite design.
- Revalidate Jira access before displaying saved reports. No offline archive
  bypass. Authorize each component and export without exposing restricted
  historical/comment/removed-scope data.
- Preserve current metric formulas and clearly label their time basis.
  Do not redesign metrics to use historical estimates in this release.

Preserve the existing UI, routes and non-sprint workflows. Implement durable
database-first sprint data, independent ticket/enrichment/metric loading,
and the security, HTTP, identity, migration, database, deployment and
observability fixes across every affected call site.

Execute milestones M00 through M09 in dependency order. Start by verifying
the current repository and test baseline. Implement working increments;
do not stop after restating the plan or fixing only the UI overlay.

Update implementation-status.md as each finding gets code and actual test
evidence. All SV01-SV12 and PR01-PR08 rows must be accounted for. Additional
related fixes listed in the master plan are included. Do not mark a milestone
complete merely because files exist or a source-text test passes.

Use injected/synthetic Jira and Tableau fixtures for local tests. Exercise
queue/concurrency/migrations/backup tests on real temporary file-backed WAL
SQLite, not only an in-memory database. Run meaningful browser tests and
verify XLSX output. Never run live Jira rule creation, the standalone TCI
updater, destructive production commands or production migrations as a test.

Existing tests that expect the CSRF bypass and unsafe generic rule-create
fallback must change as explicitly documented; do not preserve those bugs
to keep tests green. Preserve supported formulas, aliases and route behavior.

There are no pending product decisions. Routine implementation choices are
specified or can be resolved within these contracts. If actual Jira/server
capabilities prevent a requirement, implement the documented honest
unavailable path and state the concrete staging/release limitation. Do not
invent server behavior, silently weaken access checks, or claim an unrun gate
passed. Ask only if a new material conflict cannot be resolved by this plan.

At completion report:
- changes by finding/milestone and where to review them;
- migration/bootstrap and exact run/deployment instructions;
- full test, browser, SQLite concurrency, backup and export results;
- measured cold/repeat data calls, authorization calls and interaction times;
- any actual staging/production checks still required.

Do not claim deployment or production readiness beyond verified evidence.
Automatic Jira freshness and historical formula redesign remain deferred.
```

## Implementation invariants to keep visible

1. Ready data is not automatically authorized data.
2. An empty completed result is a database hit.
3. A partial page scan is never a completed snapshot.
4. A stale worker can neither publish nor resurrect revoked data.
5. A failed metric/comment job does not refetch ready core tickets.
6. Start Over resets the view; it does not delete snapshots.
7. Refresh Sprints refreshes only the catalog.
8. Current names, Jira keys and history aliases resolve through one identity layer.
9. Unknown historical/metric/comment values are not numeric zero.
10. HTTP POST safety includes transport, feature fallbacks and repeated user requests.
11. SQLite writer transactions never contain Jira I/O or retry sleeps.
12. Metrics preserve existing calculations, even where time-basis labels expose differences.
13. Export contains all permitted rows of one coherent revision map, not only visible DOM rows.
14. Login/session/PAT revocation checks apply to canonical and legacy surfaces.
15. No result cache service, PostgreSQL backend or automatic Jira freshness scheduler is introduced.

## Critical-path map

```mermaid
flowchart LR
  M00[Baseline and regression evidence] --> M01[Immediate correctness fixes]
  M01 --> M02[Security and safe DB bootstrap]
  M02 --> M03[Shared adapters and calculations]
  M03 --> M04[SQLite schema and coordination]
  M04 --> M05[Durable import worker]
  M05 --> M06[DB-first authorized APIs]
  M06 --> M07[Independent UI and full export]
  M07 --> M08[Whole-project adoption]
  M08 --> M09[Deployment and acceptance]
```

No execution is requested merely by opening this file. The copy/paste prompt is for the user's chosen implementation task.
