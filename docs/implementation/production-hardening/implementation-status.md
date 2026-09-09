# Implementation ledger

Plan prepared 2026-09-09. **No remediation implementation has started in this planning task.** This file is initialized for GPT Sol to update with actual evidence. The earlier analysis ran 69 passing baseline tests and synthetic probes; those are not passing tests of the proposed fixes.

## Decisions

| Decision | Confirmed choice |
| --- | --- |
| Database | SQLite only; no PostgreSQL implementation |
| Saved report access | Revalidate Jira access before display and export |
| Metric definitions | Preserve existing calculations and label time basis |
| Freshness | Automatic Jira refresh deferred |
| UI | Preserve existing interface and workflows |

## Milestones

| Milestone | Status | Code / test evidence | Next action |
| --- | --- | --- | --- |
| M00 baseline | Not started | — | Verify current checkout/runtime/tests and create fixtures |
| M01 immediate fixes | Not started | — | After M00 |
| M02 security/bootstrap | Not started | — | After M01 |
| M03 adapters/calculations | Not started | — | After M02 |
| M04 SQLite persistence/jobs | Not started | — | After M03 |
| M05 import pipeline | Not started | — | After M04 |
| M06 authorized APIs | Not started | — | After M05 |
| M07 UI/export | Not started | — | After M06 |
| M08 project-wide adoption | Not started | — | After M07 |
| M09 deployment/acceptance | Not started | — | After M08 |

## Findings

| Finding | Status | Implementation references | Regression evidence |
| --- | --- | --- | --- |
| SV01 UI lock | Not started | — | — |
| SV02 comment blocking | Not started | — | — |
| SV03 persistence | Not started | — | — |
| SV04 pagination | Not started | — | — |
| SV05 identity | Not started | — | — |
| SV06 history | Not started | — | — |
| SV07 repeated metrics/fanout | Not started | — | — |
| SV08 board/sprint scope | Not started | — | — |
| SV09 atomic refresh | Not started | — | — |
| SV10 service/session reuse | Not started | — | — |
| SV11 HTTP config in workers | Not started | — | — |
| SV12 DB/DOM work | Not started | — | — |
| PR01 production config | Not started | — | — |
| PR02 CSRF | Not started | — | — |
| PR03 database bootstrap | Not started | — | — |
| PR04 mutation retries | Not started | — | — |
| PR05 session/account revocation | Not started | — | — |
| PR06 process deployment | Not started | — | — |
| PR07 dependencies/CI | Not started | — | — |
| PR08 operations/limits/timings | Not started | — | — |

## Deployment facts to collect

These are discovery/verification items, not undecided product direction. Do not place secrets or real report payloads here.

- Actual deployed Python/SQLite versions and absolute local DB file location.
- Actual Jira DC/ScriptRunner capability manifest, custom field IDs and access behavior.
- Actual host service/proxy topology and service-account filesystem permissions.
- Representative sprint sizes, concurrency and measured cold/repeat/authorization costs.
- Organization-approved backup frequency/retention and restored-backup verification.

## Verification runs

Append exact commands, date, environment, result and artifact references after running them. Record failures and their resolution. No new implementation test runs are claimed here yet.

## Deviations

None at plan creation. Record each necessary deviation with the affected contract/finding, evidence, chosen resolution and tests. Do not use this section to silently waive a requirement.
