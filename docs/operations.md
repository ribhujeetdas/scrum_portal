# Operations And Logging

## Logging

Logs are JSON by default and include request correlation fields:
- `request_id`
- `method`
- `path`
- `endpoint`
- `status_code`
- `duration_ms`
- `user_id`
- `eid`

Every frontend request should send `X-Request-ID`. The backend returns the same header on responses.

External Jira/Tableau failures include:
- `event`: normalized as `<service>.request.failed` or `<service>.response.invalid_json`
- `external_service`: `jira` or `tableau`
- `external_operation`: HTTP method and path
- `external_endpoint`: Jira/Tableau endpoint path
- `external_status_code`
- `external_response_snippet`: sanitized response body snippet

Handled feature failures use stable event names, for example:
- `automation.rule_copier.copy_failed`
- `automation.sprint_viewer.issues_failed`
- `settings.projects.board_list_failed`
- `settings.tableau_custom_views.validate_failed`
- `reports.tci.csv_failed`
- `reports.tci.link_details_failed`

## Trace By X-Request-ID

1. Capture the `X-Request-ID` from the browser network tab or UI logs.
2. Search `logs/app.log` for `"request_id":"<id>"`.
3. Start with the final `request.complete` record to confirm `path`, `endpoint`, `status_code`, and `duration_ms`.
4. Review earlier records with the same `request_id`, especially `event`, `feature`, `operation`, `user_id`, `eid`, and `exception`.
5. If Jira or Tableau failed, inspect `external_service`, `external_operation`, `external_status_code`, and `external_response_snippet`.
6. Use `client.event`, `fetch.http_error`, or `fetch.network_error` records to connect browser-side failures to the same request flow.

## Troubleshooting 500s

1. Follow the request ID trace above.
2. Check the `exception` field for the Python stack trace.
3. For handled integration failures, check both the feature event and any adjacent `<service>.request.failed` event.
4. Do not paste PATs, tokens, or passwords into tickets. Logs redact known secret patterns, but tickets should still contain only request IDs and sanitized snippets.

## Production Defaults

Recommended production values:

```text
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_TO_CONSOLE=false
LOG_WERKZEUG_LEVEL=WARNING
LOG_URLLIB3_LEVEL=WARNING
LOG_SQLALCHEMY_LEVEL=WARNING
TRACE_SPRINT_VIEWER=false
TRACE_JIRA_JQL=false
TRACE_SPRINT_VIEWER_API=false
TRACE_SPRINT_VIEWER_UI=false
SESSION_COOKIE_SECURE=true
REMEMBER_COOKIE_SECURE=true
```

## Process Model And Health

Run Waitress and `python -m workers.sprint_import_worker` as separate supervised processes on one host. They must use the same environment, application revision, Fernet key, and absolute local SQLite file. The worker owns one core/access lane and two enrichment lanes; a database leader lease rejects accidental duplicate worker processes.

Use `/health/live` for process liveness, `/health/ready` for database/WAL/worker admission readiness, and `/health/worker` for the worker heartbeat. These checks do not call Jira or expose filesystem paths or secrets.

## Migration, Backup, And Restore

Before a schema migration, stop worker claiming and web writes, drain requests, and record the current application and migration revisions. Create an online backup and verify it:

```powershell
flask backup-db --destination D:\ScrumPortal\backups\portal-pre-migration.db
flask setup-db --check
flask setup-db --apply
flask check-db
```

Run a restored-backup drill against a different absolute local file and the same Fernet key, without live Jira calls. Restore production only while both processes are stopped. Keep daily online backups for 14 days plus every pre-migration backup on an encrypted, access-restricted volume. This gives an RPO of up to 24 hours; writes after the selected backup are lost during restore.

SQLite WAL, SHM, and database files must remain on local persistent disk. SMB, NFS, cloud-synchronized folders, and multi-host sharing are unsupported. Do not copy only the main database file while processes are writing.

## User And Credential Revocation

Use `flask disable-user`, `flask enable-user`, `flask revoke-user-access`, and `flask set-user-password` with exactly one of `--user-id` or `--identifier`. These commands update access/session epochs and revoke active server sessions, report grants, scopes, and jobs. `manage_users_sqlite.py` is a compatibility wrapper around the same application services and no longer exposes arbitrary updates or hard-delete cascades.

Use `flask revoke-user-sessions` when Jira scopes should remain valid. Sprint operations are explicit: `flask rebuild-sprint --user-id ... --board-id ... --sprint-id ...` creates a candidate generation while the active report remains readable; `flask retry-job --job-id ...` restarts only an unleased failed job. `flask purge-staging --older-than-days 7 --dry-run` previews safe staging cleanup and requires `--apply` to mutate. `flask purge-snapshot --snapshot-id ...` is a dry run unless `--apply` is supplied and refuses active/candidate snapshots.

## Sprint Snapshot Rollout

Deploy additive migrations and the worker while `SPRINT_VIEWER_MODE=direct`. Verify WAL and worker health, then use `SPRINT_VIEWER_SNAPSHOT_USER_IDS` for selected users or set `SPRINT_VIEWER_MODE=snapshot` for all users. If admission regresses, return affected users to corrected direct mode, stop worker claiming gracefully, retain snapshot/job data for diagnosis, and deploy a forward fix. Do not downgrade the database to remove stored snapshots.
