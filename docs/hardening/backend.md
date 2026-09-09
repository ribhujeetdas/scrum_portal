# Backend contracts: SQLite, Jira, security and APIs

Read [the master plan](README.md) first. This document fixes implementation choices within the user's requirements: SQLite only; live Jira access revalidation; existing metric formulas retained. No PostgreSQL implementation is permitted.

## B01. SQLite process and transaction model

Production has one local persistent SQLite file, one Waitress web process initially, and one supervised worker process with three lanes (one access/core lane, two enrichment lanes). Web and worker run on the same machine. The worker's main loop maintains heartbeats independently of lane execution. This is a bounded single-host design, not an HA/multi-host deployment claim.

- Use Python 3.12 with a maintained runtime linked to a patched SQLite. Inspect `sqlite3.sqlite_version` and record it in the deployment manifest. SQLite's documented WAL-reset race is fixed in 3.51.3 and later and identified backports; accept 3.51.3+ by default, or an explicitly verified official/vendor backport. Do not assume Python's version determines SQLite's version, or replace runtime DLLs ad hoc. The isolated planning runtime was Python 3.12.14 / SQLite 3.53.1; the production runtime remains to be checked. [SQLite WAL fix](https://www.sqlite.org/wal.html)
- SQLAlchemy file-backed engine uses `NullPool`, configured once in app/worker composition. Connections are cheap and short lived; do not retain ORM sessions during HTTP waits. Configure connection events for `foreign_keys=ON`, `busy_timeout=5000`, `synchronous=FULL`; bootstrap enables WAL and subsequent startup verifies it. Validate absolute DB paths and filesystem permissions.
- Reads are short transactions with stable component revision IDs. No streaming HTTP response keeps a SQLite read transaction alive. Load a bounded page, close transaction, then serialize/send.
- Writes that coordinate state use a dedicated short connection transaction beginning with `BEGIN IMMEDIATE`. Choose SQLAlchemy's manual-BEGIN event approach: set sqlite3 connection `isolation_level=None`, and have the SQLAlchemy begin event issue `BEGIN DEFERRED` by default or `BEGIN IMMEDIATE` for a connection execution option whose values are strictly whitelisted. Set that option before beginning the transaction. Do not also enable a competing sqlite3 autocommit transaction strategy, issue nested BEGIN, or interpolate request text into the mode. Select, validate, mutate and commit there. Never set every read transaction to immediate; test actual emitted BEGIN/COMMIT and rollback behavior on the pinned runtime. [SQLAlchemy SQLite transaction control](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)
- Parse/normalize Jira data outside transactions. Stage at most 100 issue rows or a bounded 1 MiB payload per write batch initially. Aim for under 100 ms write-lock hold time on the agreed host; measure separately from time waiting for the lock.
- Within the five-second transaction budget use SQLite's busy timeout; do not multiply it with another unbounded retry loop. A contended web mutation returns sanitized 503 + Retry-After. A worker defers without consuming a Jira-transient attempt when no upstream work happened.
- Never share a SQLAlchemy Session or requests.Session between threads. Disabling `check_same_thread` does not make either object thread-safe.
- Use SQLite server expressions for persisted lease/bucket time and a monotonic process clock for elapsed HTTP time. Clock jumps may cause lease reclaims; fencing must still prevent an old writer publishing.
- Automatic WAL checkpointing may retain its 1,000-page default initially. Observe WAL size and long read transactions. An operator idle checkpoint uses PASSIVE; do not run TRUNCATE/VACUUM in an API request or delete WAL/SHM files while processes are live.

## B02. Data model and constraints

Use SQLite `INTEGER PRIMARY KEY` for surrogate rows and opaque UUID strings (36 chars) for externally referenced snapshots/views/jobs. External Jira issue IDs are validated decimal strings rather than signed 32-bit integers. Board/sprint IDs are positive bounded integers. Store UTC instants consistently; keep existing timestamp column representations compatible and serialize ISO 8601 UTC. New points use finite decimal-compatible values; serialize numbers at the API boundary with the current rounding behavior.

JSON payloads use SQLAlchemy JSON backed by SQLite TEXT. Validate shapes in application code; do not require PostgreSQL JSONB, enums, arrays or advisory locks. State columns are text with check constraints. Add indexes only for the lookups described below; do not index entire raw JSON payloads.

### Identity, security and source tables

| Table/model | Required fields and constraints |
| --- | --- |
| Existing `users` / `User` | Add `session_epoch INTEGER NOT NULL DEFAULT 1`, `jira_credential_epoch INTEGER NOT NULL DEFAULT 1`, `access_epoch INTEGER NOT NULL DEFAULT 1`. Add server-side auth session tracking as below. Keep hashes, EIDs, encrypted PAT bytes, relationships and public imports. |
| `auth_sessions` | `id` opaque UUID PK, `user_id` FK, `session_epoch`, `created_at`, `expires_at`, `revoked_at`. Cookie stores the opaque ID and user/session epoch; no PAT/grant contents. Index `(user_id, revoked_at)` and `expires_at`. The current explicit absolute session timeout remains authoritative. |
| `jira_sources` | `id` PK, unique operator `source_key`, canonical configured base URL (origin plus context path), configuration fingerprint, enabled flag. No credentials. Once source identity changes, allocate a new source; do not silently repoint old data to another Jira installation. |
| `jira_scopes` | `id` UUID PK, `user_id`, `source_id`, credential epoch, access epoch, revoked_at. Unique `(user_id, source_id, credential_epoch, access_epoch)`. FK to user with cascade for actual user deletion. Revalidate current epochs on every repository call. |
| `jira_principals` | `id` PK, source ID, namespace (`dc_key`, future namespace only if capability explicitly supports it), external stable ID, display label, last observed time. Unique `(source_id, namespace, external_id)`. Not an account list endpoint. |
| `jira_principal_aliases` | principal FK, source, alias namespace, exact alias value, normalized lookup value where valid, observed/valid-from/valid-to timestamps, evidence kind, ambiguity flag. An alias may not map to two principals over the same validity period without being marked ambiguous. Enforce active alias uniqueness with a partial unique index only for verified unambiguous aliases. Historical username reuse must not merge distinct people. |

Avoid storing or exposing global principal directory metadata beyond what the user can already see in their scoped snapshot. Principal labels/aliases in responses come from that snapshot's authorized observations, not an unrestricted global lookup.

### Catalog and snapshot tables

| Table/model | Required fields and constraints |
| --- | --- |
| `sprint_catalogs` | `id` PK, scope FK, board ID, current revision number, next revision number; unique `(scope_id, board_id)`. A ready revision containing zero sprints is a valid catalog. |
| `sprint_catalog_revisions` | catalog FK, revision, state, requested filter/year basis, started/completed times, expected/received counts, safe failure code; unique `(catalog_id, revision)`. |
| `sprint_catalog_items` | catalog revision FK, sprint ID and existing sprint metadata fields; unique `(catalog_revision_id, sprint_id)`. Index revision/sprint ID. Preserve dates as parsed values plus source strings if parsing fails. |
| `sprint_snapshot_series` | UUID ID, scope FK, board ID, sprint ID, schema version, query version, calculation version, next generation, active snapshot ID nullable, candidate snapshot ID nullable. Unique `(scope_id, board_id, sprint_id, schema_version, query_version, calculation_version)`. Pointer updates validate that target belongs to the same series. |
| `sprint_snapshots` | UUID ID, series FK, generation, sprint metadata copied at import, schema/query/calculation versions, created_at, collection_started_at/ended_at, aggregate status, public response revision, invalidated_at, failure code. Unique `(series_id, generation)`. Metadata does not float when a later catalog is refreshed. |
| `sprint_components` | ID, snapshot FK, component key, state, published_revision_id nullable, next revision integer; unique `(snapshot_id, component_key)`. Keys: `core`, `history`, `comments`, five metric category keys, `metrics`. |
| `sprint_component_revisions` | ID, component FK, revision, state, producer job/fence, started/completed times, expected/received/unique counts, input revision map, data quality (`verified`, `provisional`, `unavailable`), safe error code, output JSON; unique `(component_id, revision)`. Published revisions are immutable. |
| `sprint_issue_rows` | core revision FK, Jira issue ID, issue key, source project ID/key, current assignee principal or unresolved identity, current points/status/type/subtask flag, source updated timestamp, summary, parent/epic/application fields; unique `(core_revision_id, jira_issue_id)`. Index `(core_revision_id, principal_id, jira_issue_id)` and `(core_revision_id, jira_issue_id)`. |
| `sprint_history_rows` | history revision FK, issue ID, historical status/assignee/points, compact normalized relevant history or provenance, field completeness/fallback reason, carryover marker with certainty; unique `(history_revision_id, jira_issue_id)`. Index `(history_revision_id, historical_principal_id, jira_issue_id)`. References a core revision through the component input map. |
| `sprint_comment_rows` | comments revision FK, issue ID, comment ID, canonical author or unresolved identity, created time, visibility metadata fingerprint if available. Unique `(comments_revision_id, issue_id, comment_id)`. No bodies. Persist per-issue total/verified-count/completeness in component output or normalized summary rows. |
| `sprint_metric_memberships` | metric category revision FK, issue ID/key, source project ID/key, point value at metric collection, source updated time; unique `(category_revision_id, jira_issue_id)`. Include membership for all categories, not just scope-added keys. |

Component state machine: `missing -> queued -> running -> ready`; `running -> failed|unavailable|cancelled`. Failed may transition to queued through an explicit retry with a new staging revision. Unavailable is a terminal capability/data-availability result, not the default for network errors. Published data is never overwritten by failed staging.

`metrics` depends on five ready categories; zero matching issues is a ready category with zero count and points. History/comments may be unavailable with explicit per-field output labels. A full report requires all core rows and all metric categories, and terminal history/comment status; see export rules. Snapshot `response_revision` increments when a component publishes or its public state changes, never on a no-op poll.

### Operational tables

| Table | Required fields and indexes |
| --- | --- |
| `background_jobs` | UUID ID, job type, scope, snapshot/catalog/access-view target, component key, requested revision, dedupe key, state (`queued`,`running`,`retry_wait`,`succeeded`,`failed`,`cancelled`), priority/lane, timestamps, available_at, attempts/max_attempts, resume_kind (`new`,`continuation`,`restart`), attempt_started_at, cursor/progress JSON, lease_owner, lease_until, fence integer, leader epoch, safe error code, request correlation ID. Partial unique index on dedupe key for active states; queue index `(lane,state,available_at,priority,created_at)`. Use nullable FK target columns plus a check that exactly the target required by job type is present. |
| `worker_leaders` | leader name PK, owner UUID, epoch, lease_until, last heartbeat, application/schema version. One leader `sprint-worker` for the database. |
| `jira_request_slots` | source ID + slot number PK, class, owner token, lease expiry, fence. Four configured slots initially. No token/header payload. |
| `report_views` | UUID ID, user/session/scope FK, snapshot ID, creation/expiry, client action nonce, base access state, core/history/comments/metric access states, verified input revision map, access error code. Unique `(auth_session_id, client_action_nonce)`. Bound to one view; not shared across tabs/users. |
| `rate_limit_buckets` | logical operation, salted/HMAC subject key, window start, count, expiry; composite unique key. Atomic update under short SQLite write transaction. Store neither raw credentials nor arbitrary payload. |
| `external_operations` | UUID operation ID, user/scope, logical operation, idempotency key, sanitized request fingerprint, state (`prepared`,`sending`,`succeeded`,`rejected`,`unknown`), external result ID if known, timestamps, safe failure code. Unique `(user_id, operation, idempotency_key)` plus a partial unique `(user_id, operation, request_fingerprint)` for sending/unknown states. Restrict outcome payload to data required to present a previous result. |

FK cascades must be explicit and tested with foreign keys enabled. Table deletions should not rely on ORM cascade when code uses bulk SQL. Jobs and views must become invalid immediately when scope is revoked, even if physical cleanup is delayed. Never enqueue a plaintext PAT, serialized cookie or ORM user object.

## B03. Snapshot get/create and publication

Repository APIs (names can be adapted, semantics cannot):

```python
find_current_scope(user, source) -> JiraScope
require_saved_board(scope, board_id, project_key=None) -> BoardSelection
require_catalog_sprint(scope, board_id, sprint_id) -> SprintMetadata
get_or_create_series(scope, selection, versions) -> SnapshotSeries
ensure_candidate(series, reason) -> Snapshot
enqueue_component(snapshot, component_key, request_id) -> JobOrExisting
read_component(scope, view, snapshot_id, component_key, revision=None) -> Component
publish_component(job_id, fence, leader_epoch, staged_revision_id) -> bool
invalidate_scope(user_id, reason) -> None
```

Get/create transaction: `BEGIN IMMEDIATE`; validate current user/epochs and saved scope; select unique series; insert if absent; return active compatible snapshot if complete; otherwise return/reuse candidate; allocate generation atomically; insert required job(s) with conflict-safe active dedupe; commit. Do not fetch Jira here. If a finished snapshot contains zero issues, return it. Missing history/comments/metric categories create only their missing jobs.

A manually rebuilt candidate can expose progress to its requesting operator, but normal visitors keep seeing the last complete active snapshot. The first-ever candidate can expose a ready core while other components run. Publication sets component pointer, public state/revision and dependent jobs in one transaction. When the candidate satisfies report completeness, set series active pointer and clear candidate pointer atomically. Never mix old-generation tickets with new-generation metrics.

Every publication checks: job running, matching owner/fence/leader epoch, unexpired lease, current user enabled and epochs equal, snapshot not invalidated, expected component input revisions unchanged. Read current user/epoch values through a fresh SQL query in that transaction, not a stale ORM identity-map object. A stale worker must receive false/LeaseLost and discard its attempted publication. A newer failure-recovery attempt may reuse no incomplete rows from an older attempt; release 1 restarts that component into a new revision. Deliberate healthy continuation is different, as specified below.

SQLite uniqueness is the authority for simultaneous first reads. An HTTP duplicate waits only for a short DB transaction, then receives the same snapshot/job. No Jira call is made by a losing contender. Integrity errors need rollback and scoped reread; do not swallow arbitrary DB errors as duplicate success.

## B04. Worker claiming, priorities and failure semantics

On startup, acquire `sprint-worker` leadership with a short immediate transaction. If an unexpired different owner exists, exit with an actionable already-running status. Expired leadership increments epoch. A new leader may recover old jobs, but no old leader can publish after epoch changes.

Claim algorithm:

```text
BEGIN IMMEDIATE
  read DB time
  verify current leader owner/epoch/lease
  select one eligible job for this lane, available_at <= now,
      ordered by effective priority, created_at, id
  conditional UPDATE state=running,
      attempts=attempts+(1 if resume_kind in [new,restart] else 0),
      lease_owner=worker_run_uuid, lease_until=now+120,
      fence=fence+1, leader_epoch=current_epoch
  retrieve claimed record (RETURNING or same transaction reread)
COMMIT
perform external or CPU work outside transaction
```

Core/access lane services authorization checks first, then catalog/core jobs in FIFO order with bounded fairness: at most three consecutive access work units when core/catalog is waiting, then one oldest core/catalog unit. Enrichment lanes rotate across snapshots/components after a page or issue work unit so a comment-heavy import does not monopolize both lanes indefinitely. Core lane never runs metrics while core/access is queued. A healthy job yields with `resume_kind=continuation`, preserving its attempt start time and staging revision; the next claim atomically adopts that revision's producer fence and does not increase attempts. A failure/expired-lease recovery sets `resume_kind=restart`, allocates a new staging revision and increments attempts. This distinction must be represented in persisted state, not guessed from cursor presence.

Heartbeat every 15 seconds uses its own connection. Extend job leases with matching fences; losing heartbeat/leadership stops new network batches. A request already on the wire may finish, but its result is fenced. Leader lease 120 seconds, process health heartbeat 15 seconds; readiness reports stale after 60. Graceful shutdown stops claiming, continues heartbeat while draining up to configured 90 seconds, and then marks unfinished jobs retryable where safe. The next leader reclaims expired read-only jobs.

At most four app-originated Jira requests per source, globally across web/worker; no more than two background category/history/comment calls. Slot acquisition/release is a separate immediate transaction, with random owner + fence and lease longer than the 60-second HTTP attempt budget. No slot is held during retry backoff or CPU calculation. Slots protect all Jira service call sites, including Settings and Rule Copier; pre-database rollout direct mode uses corrected bounded per-process requests until slots exist. Anonymous signup may use source slots without a user scope and has independent admission limits.

Keep job admission and permission checks responsive if slots are full: web routes return processing/deferred state; workers reschedule rather than block a DB transaction. Jira 429 honors bounded Retry-After with jitter; long waits update available_at. Error classification:

| Condition | Job/component result |
| --- | --- |
| 401/403 or revoked account/scope | Stop current work, revoke view access, cancel/fail affected jobs with `JIRA_ACCESS_DENIED`; no automatic authentication retry. |
| 404 missing board/sprint/issue | Capability/context-specific `SOURCE_NOT_FOUND` or access-unavailable; never interpret an arbitrary 404 as an empty sprint. |
| 429, transient connection failure, 502/503/504 | Bounded retry_wait; maximum 3 job attempts including initial attempt, each HTTP operation at most 3 read attempts. Record total upstream attempts. |
| Invalid JSON/schema, no-progress pagination, inconsistent page metadata | Fail component with actionable safe code; no infinite retries. An explicit retry can restart after server/data correction. |
| Unsupported changelog capability | `history=unavailable`, per-field fallback labels; no fake success. |
| DB busy before upstream work | Defer/503 as appropriate, not counted as a Jira attempt. |
| Disk full / persistent DB I/O failure | Stop admission, fail readiness, retain last published data; no delete-to-make-space automation. |
| Expired lease | New fence/attempt may take over; stale writes are rejected. |

Job retries and HTTP retries must have an explicit combined ceiling; never allow “3 retries” to ambiguously mean 3 attempts in one layer and 4 in another. Log both numbers. No background mutation job for Rule Copier in this release.

## B05. Live authorization before stored report reads

This is mandatory per user decision. A completed DB data hit does **not** promise zero Jira calls overall. It avoids refetching ticket fields/recalculating metrics but still checks authorization. First-view authorization may be expensive for restricted comments; measure it separately.

1. Every Fetch Issues action creates a fresh `report_view`, bound to the authenticated server-side session, scope and snapshot. Duplicate transport attempts with the same client action nonce reuse that view; a new action/tab does not reuse it accidentally.
2. Validate portal user active/not deleted, live auth session/not expired, saved board/project, source and credential/access epochs immediately. Board scope is a saved configuration entitlement, not proof of all Jira issue permissions.
3. Perform a fresh Jira `/myself` ownership/enabled check for the new view with the stored PAT. Existing five-minute PAT identity reuse may remain for other workflows, but it does not authorize stored report visibility by itself.
4. Recheck Jira board visibility and board/sprint association using the deployed DC capability. Validate a sprint against the authorized board's catalog/API relation, not originBoardId alone; shared sprints can have a different origin. Persisted catalog completion proves imported association, but current board access must still be validated.
5. For core visibility, query all stored core issue IDs in bounded numeric-ID JQL batches with minimal `id,key` fields and supported stable ordering. Exact returned ID set must contain the required set. A project permission check alone does not cover issue-security schemes. Do not silently filter missing IDs and retain old global totals: withhold the core component with `REPORT_ACCESS_CHANGED` and offer operator/user guidance to rebuild under current access. On a first-ever import, the fresh authorized Jira responses may supply this evidence for the requesting view if actor/epochs/revisions and grant age match; do not immediately repeat equivalent reads just to validate newly fetched data. Old snapshot data never creates a fresh grant by itself.
6. For metric visibility, independently validate the union of issue IDs in all five category memberships, including removed-scope tickets absent from core. If this fails, tickets can remain visible when core access passed, but all affected metric totals/export remain withheld. Do not reveal counts of forbidden IDs.
7. History can be exposed only when the deployment's Jira permission contract establishes that issue visibility also permits its stored historical fields. If a plugin applies additional history restrictions, use its supported verification mechanism. Unsupported verification means that historical component is unavailable/withheld, not authorized by `/myself`.
8. Comments have issue-level plus potential per-comment restrictions. Before exposing stored comment counts/author-derived statistics, enumerate current visible comment IDs for the relevant issues (bounded/paginated) and compare the stored relevant ID set and visibility evidence. This may require the Jira comments API even on a DB hit. Discard bodies immediately and do not refresh snapshot content as a side effect. If a stored comment is deleted/restricted or current visibility cannot be verified, withhold that comment-derived component; do not leak its old count. Comment-total fields require the same protection.
9. A component access grant lasts at most 300 seconds and never beyond the auth session expiry. It is tied to exact component revisions and snapshot generation. Expiry initiates fresh verification before further reads; no sliding expiry on polls. Initial/newly published components require their own verification. This is a short-lived authorization record, not a new Jira result-cache service.
10. The UI displays “Access checked at …” if useful and stops serving/clears protected state after 401/revocation or grant expiry. Existing downloaded files cannot be recalled; never claim otherwise. For a final report download, create a fresh export authorization check rather than rely solely on earlier display permission.

Jira outages: completed data may remain stored, but a new view cannot display it without successful required authorization. Return `ACCESS_CHECK_UNAVAILABLE` with retry, not a fabricated empty report or automatic offline mode. Already-issued grants have the documented maximum five-minute window; detected local revocation invalidates them immediately. These checks establish point-in-time authorization, not an atomic transaction with subsequent Jira permission changes.

No approval question remains for this policy; it was selected. A deployment that cannot provide the required history/comment visibility evidence must show those parts as unavailable and document the concrete limitation. Do not claim strict permissions while checking only `/myself`/project ADMINISTER_PROJECTS.

## B06. Jira pagination and input collection algorithms

### Jira offset pagination

Apply to sprint list, issues, JQL categories, comments, Settings board list and board/project association list. Endpoint adapter declares collection key and metadata fields; do not use one generic parser that silently guesses payload shapes.

1. Validate response object and collection array; validate numeric metadata excluding booleans and negatives. Record returned `startAt`, `maxResults`, `total`, `isLast` if present.
2. Requested page size is a hint. Advance by the actual consumed server page count, never requested maxResults or deduplicated count. If returned startAt differs from requested offset, fail unless the endpoint's documented contract explicitly explains it.
3. Deduplicate by stable Jira ID while retaining unique membership and summing each issue once. Do not deduplicate across different snapshots or metric categories. Repeated ID with conflicting values within one import marks source inconsistency; restart that component once, then fail rather than randomly choosing.
4. Explicit `isLast=true` ends pagination only if it is consistent with advertised totals. `isLast=false` requires continued progress even when the page is smaller than requested. When total exists, continue until actual consumed offset reaches it and verify unique cardinality where total is an issue/item count.
5. When neither total nor last flag exists, continue nonempty pages until a verified empty page; do not stop merely because the requested size was not filled. Endpoints incapable of proving complete traversal must be explicitly unsupported for complete snapshot imports.
6. Empty page before advertised end, repeated page fingerprint, offset not advancing, contradictory flags/totals, exceeded max pages/items or invalid records cannot publish ready. Return a distinct safe completeness error.
7. Use supported `ORDER BY id ASC` for JQL membership searches. Do not claim offset paging is an atomic source snapshot; track collection interval, membership count and changed `updated` evidence. Retrying a changed scan starts from page zero into a new component revision.
8. For sprint-year filtering, pagination counts are unfiltered source counts. Filter only after collecting each source page; never use filtered list length to advance or terminate.

### Tableau pagination

Keep Tableau's pageNumber/pageSize/totalAvailable model separate. Use returned pageSize and pageNumber metadata, not `page_number * requested_page_size`, to determine progress. Validate numeric strings as the API may return them as text. Continue until the requested view is found or verified completion; detect repeated pages/no progress. Preserve sign-out in finally, including pagination/parse failure, and preserve the existing no-ID-filter workaround.

### Core fields and hydration

Core request fields: `summary`, configured story-point field, `issuetype`, `status`, configured application field, `epic`, configured epic-link field, `assignee`, `parent`, `project`, `updated`. Request only fields supported by the deployed endpoint. Do not request comments/changelog as prerequisites to core publication. Where the API necessarily returns them, discard unnecessary bodies and schedule proper completeness checks independently.

Historical closed sprint metadata uses actual completion as cutoff. Jira `updated` timestamps and category collection timestamps are provenance; no automatic freshness trigger. Category imports fetch issue ID/key, configured point field, project and updated timestamp. Missing configured fields are explicit capability failures or per-field unavailable values, never silently reinterpreted as all tickets unestimated.

## B07. Identity, history and calculation semantics

### Canonical identity

For Jira DC use its stable user `key` as the canonical external principal where present. Current `name` is an alias, displayName is a label. Resolve all three paths—current assignee, changelog values, comment author—through the same resolver. Existing portal `User.jira_key` helps only for registered portal users; sprint participants need not have portal accounts.

Resolve aliases in batches/per unique unknown identifier, not once per ticket/comment. Prefer identities observed in authorized Jira payloads; use DC lookup by key/username only when needed and supported. Persist provenance and ambiguity. Strip surrounding whitespace for lookup; do not blindly lowercase stable keys or collapse two identities with matching display names. Username normalization must match verified DC semantics. Missing assignee is one reserved unassigned identity, not an unresolved user's displayName.

If historical `from` is a stable key, use it. If only fromString display text is available, preserve an unresolved historical reference; do not merge by display text or map it to the currently assigned user. For ambiguous reused usernames, keep separate unresolved records until verified. Use issue ID as a tiebreaker for stable presentation when identities remain unresolved. Relevant-comment inclusion uses canonical principal IDs, not strings of different namespaces.

### Historical reconstruction

Start with current assignee/status/points, then walk all relevant events after cutoff in descending timestamp order, reversing each change. Explicit `from=null` means unassigned/null; it must not fall back via boolean `or` to the current value. Preserve zero story points. Field ID is preferred to localized field display names, with existing compatible aliases accepted.

Complete history with no post-cutoff changes means current values are valid at cutoff. Missing/truncated/unsupported history does not. Inspect page totals/start offsets and fetch all supported history pages; do not invent a Cloud changelog endpoint in a DC installation. If full history cannot be obtained, record fallback per affected field and retain visibly current values. Unparseable event timestamps make historical certainty unavailable; do not silently sort them as valid ancient events.

Carryover marker keeps the existing meaning: evidence of multiple sprint memberships in history. Parse supported structured/numeric/comma-separated/list-form IDs using verified fixtures; do not treat arbitrary digits in a sprint name as membership. If membership history is incomplete, marker is unknown rather than false. Ticket carryover quality statistic is distinct from scrum carryover formula; label them to avoid conflation.

### Existing metric definitions to preserve

Let O=original commitment, CO=completed original, TC=total completed, A=added scope, R=removed scope. Preserve the exact current ScriptRunner predicates from `compute_sprint_metrics_parallel`; express them in one versioned query builder using validated numeric board/sprint IDs:

| Category | Predicate |
| --- | --- |
| O | `(completeInSprint OR incompleteInSprint OR removedAfterSprintStart) AND NOT addedAfterSprintStart` |
| CO | `completeInSprint AND NOT addedAfterSprintStart` |
| TC | `completeInSprint` |
| A | `addedAfterSprintStart` |
| R | `removedAfterSprintStart` |

All predicates use the existing `issueFunction in ...` syntax with board/sprint arguments and `issuetype IN standardIssueTypes()`. Preserve the parentheses and category semantics. Sum the finite point field values returned by each query at collection time. Persist input memberships for all five categories, even if only A keys are currently displayed. Do not replace these queries with core-ticket filtering.

For both point and count dimensions: completed-added=`max(0,TC-CO)`; carryover=`max(0,O-CO-R)`; net scope=`A-R`. Percentages: predictability=`100*CO.points/O.points`; delivery-vs-commitment=`100*TC.points/O.points`; added scope=`100*A.points/O.points`; removed scope=`100*R.points/O.points`; scope change=`100*(A.points+R.points)/O.points`; spill=`100*carryover.points/O.points`. Preserve current denominator <=0 => 0 behavior **only when inputs are complete**. Round points to two decimals and percentages to one; red threshold remains strictly >20. Missing/failed inputs yield null/unavailable, not zero.

Keep all current response aliases (`committed_*`, `delivered_*`, `spillover_*`, `scope_added_*`, `descope_*`, `predictability_pct`, `spill_pct`, `scope_pct`, `spill_red`, `scope_red`) and full newer field names. Keep the current `scope_added_keys` meaning. A null story point remains unestimated for quality stats; non-finite/invalid values are excluded with a data-quality warning, not serialized as NaN/Infinity.

Existing quality/work-type calculations operate on standard (non-subtask) issues, while ticket groups include subtasks. Preserve total/standard_total and group-count meanings. Preserve relevant comments as authors in the canonical sprint team with creation time <= completion, without adding a new sprint-start lower bound. Unknown comment date at a required cutoff is unknown evidence, not automatically eligible. Recompute only after history/team and comment inputs are ready.

Time-basis labels: ticket historical values=`at sprint completion` when verified, otherwise `current Jira value; historical value unavailable`; scrum points=`Jira points at collection time`; comment-derived values=`visible comments at collection, cutoff at sprint completion`. Add collection timestamps to UI help/export. Keep formulas/version metadata in the snapshot even if different categories were collected seconds apart. Use `schema_version=1`, `query_version=1`, `calculation_version=1` for the first durable contract; bump versions only for a documented incompatible change, not every deploy.

## B08. Shared HTTP and mutation contracts

Create immutable `HttpPolicy` before requests/jobs begin: base URL, allowed origin/context path, CA/proxy policy, connect/read timeouts, total operation deadline, max response bytes, max safe attempts, retry statuses/backoff cap and operation safety. Thread workers receive values explicitly, never access Flask proxies to discover them.

Use one owned client/session per request context or lane work unit; reuse it for that unit's pagination. `close()` and context-manager support close only owned sessions; injected test sessions follow documented ownership. Request-local factories memoize within `flask.g`; teardown closes them. Worker factories create independent lane clients and close them at shutdown/job completion. Pure calculations do not construct clients.

Avoid two retry engines: choose an explicit application attempt loop with adapter retries disabled for full deadline/attempt observability, or a tested adapter that enforces the same bounds. This plan chooses **an explicit loop with adapter retries disabled**. Read-safe default methods: GET/HEAD; a search POST may opt in only through a named read-only operation. POST/PUT/DELETE default to one attempt.

Bound connect timeout by remaining deadline; stream response chunks with a cumulative decompressed-byte cap and check deadline between reads; bound read timeout by remaining budget. Use a read primitive that returns available data (for example a tested urllib3 raw `read1` loop), not a large fixed-size read that can wait indefinitely for trickled bytes. An ordinary requests timeout is not a hard total wall-clock deadline; verify slow trickle, decompression expansion and bounded reads with a local synthetic HTTP server. Document any platform DNS/socket-boundary limit rather than claim an unverified hard deadline. Always close responses, including exceptions/caps. Backoff/Retry-After sleeps cannot exceed remaining budget. Do not hold Jira slots during sleep; a worker defers a long wait instead.

Validate URLs before attaching credentials: same configured scheme/host/effective port; no userinfo; normalized path inside configured Jira/Tableau context path; reject network-path URLs, encoded traversal, unexpected origins and redirects. Disable automatic redirect following; allow only explicitly verified same-source redirect if required, bounded to one and never for an ambiguous mutation. TCI should preferably reconstruct issue detail URLs from validated issue IDs/keys rather than trust arbitrary `self` values. Do not disable TLS verification for internal certificates.

Errors retain structured upstream status, operation, retryability, transmission/outcome certainty and sanitized code. User-facing messages do not echo Jira response snippets or arbitrary exception text. Error logging may record a redacted, bounded diagnostic only behind a controlled diagnostic flag; defaults contain no full issue content/PATs.

### Rule Copier

Add `Idempotency-Key` from one browser copy action. Server `external_operations` fingerprint includes canonical source rule payload, target board/project, user and intended actor policy. Same key+same fingerprint returns the previous outcome or processing status; same key+different fingerprint returns 409. A new key with the same fingerprint cannot bypass an outstanding sending/unknown operation; return that operation reference until reconciled. A completed successful prior operation does not prevent a later explicitly initiated separate copy. Never claim exactly-once Jira mutation without upstream support.

Before sending, validate current user, saved target board/project and current Jira permission required by the workflow. Do not infer board identity solely from the first issue's project: boards may span projects. Preserve intended single target project scope; validate transformed `projects` entries cannot retain unrelated source projects.

Set operation state `sending` transactionally, then send one create outside the transaction. Successful response stores external ID/result. Known documented rejection before creation sets `rejected`; only a matching specific rejection may trigger a single actor or identifier fallback. Generic 400 text, any 5xx, timeout after send, connection reset, 2xx invalid/missing result without reconciliation, and unknown exceptions set `unknown` and stop all fallbacks. Return sanitized 409 `EXTERNAL_OUTCOME_UNKNOWN` with operation reference and guidance to inspect Jira before a new create. Do not blindly re-send on same idempotency key.

Preserve safe fallback compatibility tests using typed definitive-rejection fakes instead of an unclassified string exception. Remove broad catch-and-retry loops in `_create_rule_with_identifier_fallback` and the configured actor fallback. If deployed endpoint lacks documented rejection codes/capability, fallback is unavailable; report a clear rejection/unknown result rather than guessing success. Reads to reconcile outcomes are allowed; a rule with the same name alone is not proof that this operation created it. Provide an operator `resolve-operation` command that records verified external ID/success or evidence of definite rejection without issuing a create; audit the resolution. A process crash in sending state is treated as unknown, never automatically resent.

## B09. API contract

All JSON control inputs must be objects. Validate IDs before access/service work. Positive numeric IDs accept JSON integers or a strict decimal string for compatibility; reject booleans/floats/signs/exponents and values outside the documented 64-bit bound for board/sprint IDs. `refresh` accepts a JSON boolean only. API body limits are enforced on actual read bytes, not just Content-Length.

All APIs use `{ok,request_id,...}`. `json_ok` remains backwards compatible; add a separate `json_accepted` helper or return `(json_ok(...),202)`, never silently serialize `status_code` as a field. Error: `{ok:false,request_id,error:{code,message,retryable}}`. Sanitize JSON 400/401/403/404/409/413/429/503 uniformly on canonical and legacy routes. Unknown snapshot IDs and other users' IDs both return 404; known owned but revoked access returns 403 without leaking forbidden counts.

### Routes in snapshot mode

| Method/path | Input / behavior |
| --- | --- |
| POST `/api/automation/sprint-viewer/sprints` | Existing `{project_key,board_id,refresh:false}`. Ready catalog returns old `sprints` array plus source/catalog revision. Miss/explicit refresh returns 202 with catalog/job ID and progress; old catalog may be displayed with an explicit refresh-in-progress flag after access validation. Empty-ready returns 200 + empty list. |
| POST `/api/automation/sprint-viewer/issues` | `{board_id,sprint_id,client_action_id}`. Require a verified ready catalog association; if catalog is not ready return409 `CATALOG_NOT_READY`, and if sprint absent return404 `SPRINT_NOT_IN_BOARD` with refresh-list guidance. Authenticate/scoped get-create, initiate fresh report view authorization, enqueue missing core/components. 200 only if core ready and authorized; otherwise202. Return snapshot/view/status references. Existing issue payload fields remain in ready response. |
| POST `/api/automation/sprint-viewer/metrics` | `{board_id,sprint_id,snapshot_id?,view_id?}`. Existing totals accepted but ignored. Ensure/reuse categories for the same snapshot. Does not start another core fetch. Ready authorized result 200; pending 202. An unbound legacy caller starts an authorized view before results. |
| GET `/api/automation/sprint-viewer/catalogs/<id>/status` | Read-only scoped status for initial sprint selection/refresh. Never starts another catalog import. |
| GET `/api/automation/sprint-viewer/snapshots/<id>/status?view_id=...` | Scoped/authenticated status only; component states/revisions/progress and safe access status. No full tickets, totals or hidden issue counts before component authorization. |
| GET `/api/automation/sprint-viewer/snapshots/<id>/issues?view_id=...&revision=...&cursor=...&limit=200&principal_id=...` | Authorized stable core/history representation. Limit1–500; optional scoped principal filter; opaque validated cursor tied to snapshot/revision/order/filter. Order by stable Jira issue ID with deterministic numeric-string ordering. Never combine pages of different response revisions. |
| GET `/api/automation/sprint-viewer/snapshots/<id>/components/<key>?view_id=...&revision=...` | Authorized ready component output or 202/terminal unavailable/error. Whitelist component key; no arbitrary table/file names. |
| POST `/api/automation/sprint-viewer/snapshots/<id>/retry` | `{view_id,component,client_action_id}`. CSRF/rate-limited. Retry only failed/unavailable-if-recoverable missing component. Ready core is not refreshed. Invalid state ->409; duplicate ->same job. |
| POST `/api/automation/sprint-viewer/snapshots/<id>/authorize` | `{client_action_id,purpose:'view'|'export'}`. Fresh bounded permission check; returns view ID/access job or ready authorized state. Does not refresh snapshot data. |
| GET `/api/automation/sprint-viewer/snapshots/<id>/export-manifest?view_id=...` | Requires fresh export-purpose authorization and report readiness. Returns exact component revision map and bounded data-page links; 409 if report not exportable. Client generates existing XLSX from these immutable authorized revisions. |

Legacy paths remain delegates for the original three APIs; no need to invent legacy variants for new endpoints. Status uses ordinary GET and cannot enqueue jobs on expiration; browser explicitly posts authorize when needed. All URLs must be registered through authenticated wrappers, not direct undecorated feature handlers.

### Representative accepted response

```json
{
  "ok": true,
  "request_id": "request-uuid",
  "state": "processing",
  "source": "jira",
  "snapshot_id": "snapshot-uuid",
  "view_id": "view-uuid",
  "generation": 1,
  "response_revision": 2,
  "status_url": "/api/automation/sprint-viewer/snapshots/snapshot-uuid/status?view_id=view-uuid",
  "retry_after_ms": 1500,
  "components": {
    "core": {"state": "running", "revision": null, "progress": {"stage": "Loading tickets", "pages_completed": null, "total_pages": null}},
    "history": {"state": "missing"},
    "comments": {"state": "missing"},
    "metrics": {"state": "missing"}
  },
  "access": {"core": "pending", "metrics": "pending", "comments": "pending"}
}
```

HTTP 202 includes Retry-After (seconds) consistent with retry_after_ms. `source` means current result origin: DB for persisted reads, Jira for a newly importing miss; do not claim a DB data hit makes zero authorization calls. A component may be ready but access pending: do not serialize its protected payload or old result cardinality yet. Stage-only progress can display while access is pending; counts appear only when authorized evidence permits them.

Ready issue response retains `total`, `standard_total`, `total_sp`, `groups`, `stats`, `sprint`, `work_type_mix`, `historical_fallback_count`. Add snapshot/generation/response revisions, source/fetched timestamps, `field_availability`, `time_basis`, and stable principal IDs. In snapshot mode `groups` carries complete group summaries but at most200 initial issue rows across all groups; add `issues_complete`, `next_cursor`, `page_limit` and per-group data links. Totals remain full-snapshot totals. This additive paged contract is explicitly different from the old unbounded complete `groups[].issues` response; the new UI must follow cursors, and direct mode keeps its corrected legacy contract. Small snapshots <=200 can still return all rows immediately. No hidden unbounded POST response defeats the paged design. Provisional/unavailable stats fields are null or omitted with availability metadata; frontend must not coerce them to zero. Group summaries require the same authorization as tickets and are computed from the pinned core/history revisions.

Set `Cache-Control: no-store` on authenticated data, status, grant and export-manifest responses. View IDs are not bearer permissions: every request still needs the same live session/user/scope. Avoid raw view IDs in external URLs/referrers or logs; redact query strings in client diagnostics. Stable revision-bound GETs are idempotent but not publicly cacheable.

## B10. Security/admin/operational details

- Register auth/session enforcement before protected application behavior. Override `User.is_active` to reflect `active and not deleted`; do not rely on UserMixin's default active property. On epoch mismatch/disabled/deleted user, revoke session records and clear the cookie; canonical/legacy API callers get JSON 401. Login explicitly starts a new opaque session and CSRF state. No explicit GET logout/credential-mutation route is introduced; security enforcement may invalidate an expired/revoked session on any request.
- PAT updates validate ownership using Jira, then atomically encrypt/store the new PAT, increment credential/access epochs, revoke scopes/views and fence their jobs. Perform Jira validation before the write transaction; reread user/epoch before commit. A successful update must not leave old sessions with a valid Jira grant.
- Password changes increment session epoch and revoke all sessions. Account disablement/deletion does the same plus access revocation. All supported CLI/admin paths call these services; raw generic production field updates are removed from the compatibility admin script.
- On project/board deletion, revoke relevant scopes/jobs/views before commit; no detached worker can publish afterward. Actual user deletion cascades private snapshots/comments/jobs; default disablement keeps data inaccessible for controlled retention.
- DB/file/log/backup directory ACLs restrict access to the service account and approved administrators. SQLite snapshot rows are not encrypted automatically by WAL; deployment disk and backup encryption must protect stored Jira content. Do not falsely describe Fernet PAT encryption as encryption of all report data.
- Production config refuses known placeholder secret/encryption values, debug mode, unsafe host/proxy settings, in-memory/network SQLite deployment and unpatched concurrency runtime as described. Tests explicitly supply harmless keys and in-memory profiles; they may not disable production checks globally.
- Rate buckets use normalized logical routes, so aliases cannot double a limit. A login identifier is HMACed with a dedicated configured salt before persistent rate-key storage. Use trusted remote address after configured proxy processing; never trust raw X-Forwarded-For. On DB unavailability, protected mutations fail closed; diagnostic logging may drop events rather than recursively log its own failure.
- Headers: secure/HttpOnly/SameSite cookies, `X-Content-Type-Options:nosniff`, frame-ancestors restriction appropriate to this standalone app, Referrer-Policy, HSTS only under actual HTTPS production deployment. Host allowlist/proxy counts must match the deployed topology. Preserve Bootstrap 5.3.3 appearance; self-host its exact approved assets or add verified integrity metadata before a CSP restriction. Do not impose a CSP that silently breaks existing inline styles/data favicon.
- Liveness returns only process alive. Web readiness checks DB connection, expected schema and WAL configuration; include worker availability when admitting new imports. A stale worker need not block already-ready, already-authorized data reads. Worker health checks process/leader freshness and DB access, not live Jira availability on every probe. Public health output exposes no filenames, DSNs, users or stack traces.
- Logging extends existing request IDs with parent request/job/snapshot generation, component, timing, attempts, outcome and byte/page counts. Log route templates and named metric categories instead of unbounded raw JQL/URLs. Validate/truncate client-supplied request IDs. Client-log body limits apply even with missing/chunked Content-Length, sanitize URL query/fragment and secrets, and prevent log amplification loops.
- Operator commands: `setup-db`, `worker-status`, `rebuild-sprint --user-id --board-id --sprint-id`, `retry-job`, `revoke-user-sessions`, `disable-user`, `backup-db`, `check-db`, `purge-staging --older-than-days 7 --dry-run` and explicit successful snapshot purge. Resolve and validate paths before any file replacement/delete. Purge must never delete a referenced published revision or live leased job. No automatic Jira freshness job is added.

## B11. What must be verified in the deployed environment

Sol should implement fixtures/capability adapters and a read-only probe, not guess unknown server behavior. Record: exact Jira DC/ScriptRunner versions; principal key/username shapes; complete history support; issue/comment visibility behavior; real page caps; required custom fields; TLS CA chain; local SQLite file path/runtime version; and expected peak concurrent viewers. The probe uses an explicitly provided test scope and prints only capability/count/timing summaries, never issue bodies or credentials.

If a capability is absent, use the explicit unavailable path above and report its user-visible consequence. Do not add undisclosed scraping of internal Jira endpoints or infer permission from a role label. A launch report must separate software tests completed locally from staging/production checks not yet performed.
