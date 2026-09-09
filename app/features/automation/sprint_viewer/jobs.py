from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
import uuid
from typing import Any

from flask import current_app
from sqlalchemy import or_

from ....core.dependencies import jira_service, sprint_viewer_service
from ....core.http_client import ExternalServiceError
from ....extensions import db
from ....models import User
from ....services.crypto_service import CryptoService
from ....services.sprint_viewer_service import SprintViewerServiceError
from ....integrations.jira.pagination import collect_offset_pages
from .calculations import METRIC_CATEGORIES, build_scrum_metrics, metric_queries
from .models import (
    BackgroundJob,
    JiraPrincipal,
    JiraPrincipalAlias,
    JiraScope,
    JiraRequestSlot,
    ReportView,
    SprintCommentRow,
    SprintComponent,
    SprintComponentRevision,
    SprintHistoryRow,
    SprintIssueRow,
    SprintMetricMembership,
    SprintSnapshot,
    SprintSnapshotSeries,
    WorkerLeader,
)
from .repository import component_map, enqueue_job, now_utc, published_output


log = logging.getLogger("app.sprint_worker")


class LeaseLost(RuntimeError):
    pass


def _persist_principals(scope: JiraScope, issues: list[dict[str, Any]]) -> dict[str, int]:
    """Persist stable Jira identifiers and non-authoritative aliases for report rows."""
    namespace_map = {
        "account": "account_id",
        "key": "dc_key",
        "name": "legacy_name",
        "unassigned": "system",
    }
    specs: dict[str, tuple[str, str, str | None, str | None]] = {}
    for issue in issues:
        principal = str(issue.get("principal_id") or "unassigned")
        prefix, separator, external = principal.partition(":")
        if not separator:
            prefix, external = "unassigned", principal
        namespace = namespace_map.get(prefix, "legacy_name")
        specs[principal] = (
            namespace,
            external or "unassigned",
            issue.get("assignee_name"),
            issue.get("assignee_eid"),
        )
    existing = {
        (row.namespace, row.external_id): row
        for row in JiraPrincipal.query.filter_by(source_id=scope.source_id).all()
    }
    resolved: dict[str, int] = {}
    for principal, (namespace, external, display, alias) in specs.items():
        row = existing.get((namespace, external))
        if row is None:
            row = JiraPrincipal(
                source_id=scope.source_id,
                namespace=namespace,
                external_id=external,
                display_label=display,
                last_observed_at=now_utc(),
            )
            db.session.add(row)
            db.session.flush()
            existing[(namespace, external)] = row
        else:
            row.display_label = display or row.display_label
            row.last_observed_at = now_utc()
        resolved[principal] = row.id
        normalized_alias = str(alias or "").strip().casefold()
        if normalized_alias and normalized_alias != external.casefold():
            found = JiraPrincipalAlias.query.filter_by(
                principal_id=row.id,
                namespace="jira_name",
                normalized_value=normalized_alias,
                valid_to=None,
            ).first()
            if found is None:
                db.session.add(JiraPrincipalAlias(
                    principal_id=row.id,
                    source_id=scope.source_id,
                    namespace="jira_name",
                    alias_value=str(alias).strip(),
                    normalized_value=normalized_alias,
                    evidence_kind="issue_payload",
                ))
    return resolved


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def acquire_leadership(owner: str, *, lease_seconds: int = 120) -> int:
    now = now_utc()
    row = db.session.get(WorkerLeader, "sprint-worker")
    if row is None:
        row = WorkerLeader(
            name="sprint-worker",
            owner=owner,
            epoch=1,
            lease_until=now + timedelta(seconds=lease_seconds),
            last_heartbeat=now,
            application_version="1",
            schema_version="1",
        )
        db.session.add(row)
        db.session.commit()
        return row.epoch
    if row.owner != owner and _aware(row.lease_until) > now:
        raise RuntimeError("Another sprint worker holds the unexpired leader lease")
    if row.owner != owner:
        row.epoch += 1
    row.owner = owner
    row.lease_until = now + timedelta(seconds=lease_seconds)
    row.last_heartbeat = now
    db.session.commit()
    return row.epoch


def heartbeat_leader(owner: str, epoch: int, *, lease_seconds: int = 120) -> bool:
    now = now_utc()
    updated = WorkerLeader.query.filter_by(name="sprint-worker", owner=owner, epoch=epoch).update(
        {WorkerLeader.lease_until: now + timedelta(seconds=lease_seconds), WorkerLeader.last_heartbeat: now},
        synchronize_session=False,
    )
    db.session.commit()
    return updated == 1


def heartbeat_job(
    job_id: str,
    owner: str,
    fence: int,
    epoch: int,
    *,
    lease_seconds: int = 120,
) -> bool:
    now = now_utc()
    updated = BackgroundJob.query.filter_by(
        id=job_id,
        state="running",
        lease_owner=owner,
        fence=fence,
        leader_epoch=epoch,
    ).update(
        {
            BackgroundJob.lease_until: now + timedelta(seconds=lease_seconds),
            BackgroundJob.updated_at: now,
        },
        synchronize_session=False,
    )
    db.session.commit()
    return updated == 1


def claim_job(owner: str, epoch: int, lane: str) -> BackgroundJob | None:
    now = now_utc()
    lease_seconds = int(current_app.config.get("SPRINT_JOB_LEASE_SECONDS", 120))
    BackgroundJob.query.filter(
        BackgroundJob.state == "running",
        BackgroundJob.lease_until < now,
    ).update(
        {
            BackgroundJob.state: "retry_wait",
            BackgroundJob.resume_kind: "restart",
            BackgroundJob.available_at: now,
            BackgroundJob.lease_owner: None,
            BackgroundJob.lease_until: None,
            BackgroundJob.error_code: "LEASE_EXPIRED",
        },
        synchronize_session=False,
    )
    db.session.commit()
    job = (
        BackgroundJob.query.filter(
            BackgroundJob.lane == lane,
            BackgroundJob.state.in_(("queued", "retry_wait")),
            BackgroundJob.available_at <= now,
        )
        .order_by(BackgroundJob.priority.asc(), BackgroundJob.created_at.asc(), BackgroundJob.id.asc())
        .first()
    )
    if job is None:
        return None
    if job.attempts >= job.max_attempts and job.resume_kind != "continuation":
        job.state = "failed"
        job.error_code = "ATTEMPTS_EXHAUSTED"
        if job.component_key and job.snapshot_id:
            component = SprintComponent.query.filter_by(
                snapshot_id=job.snapshot_id, component_key=job.component_key
            ).first()
            if component:
                component.state = "failed"
                component.error_code = "ATTEMPTS_EXHAUSTED"
            snapshot = db.session.get(SprintSnapshot, job.snapshot_id)
            if snapshot:
                snapshot.response_revision += 1
        db.session.commit()
        return None
    old_fence = job.fence
    next_attempts = job.attempts + (1 if job.resume_kind in {"new", "restart"} else 0)
    updated = BackgroundJob.query.filter(
        BackgroundJob.id == job.id,
        BackgroundJob.fence == old_fence,
        BackgroundJob.state.in_(("queued", "retry_wait")),
        BackgroundJob.available_at <= now,
    ).update(
        {
            BackgroundJob.state: "running",
            BackgroundJob.attempts: next_attempts,
            BackgroundJob.lease_owner: owner,
            BackgroundJob.lease_until: now + timedelta(seconds=lease_seconds),
            BackgroundJob.fence: old_fence + 1,
            BackgroundJob.leader_epoch: epoch,
        },
        synchronize_session=False,
    )
    db.session.commit()
    return db.session.get(BackgroundJob, job.id) if updated == 1 else None


def _acquire_request_slot(job: BackgroundJob, owner: str) -> tuple[int, int] | None:
    scope = db.session.get(JiraScope, job.scope_id)
    if scope is None:
        return None
    now = now_utc()
    slot_class = "interactive" if job.lane == "core" else "background"
    slots = JiraRequestSlot.query.filter_by(
        source_id=scope.source_id, slot_class=slot_class
    ).order_by(JiraRequestSlot.slot_number).all()
    lease_until = now + timedelta(
        seconds=int(current_app.config.get("SPRINT_COMPONENT_MAX_RUNTIME_SECONDS", 1800))
    )
    for slot in slots:
        old_fence = slot.fence
        updated = JiraRequestSlot.query.filter(
            JiraRequestSlot.source_id == slot.source_id,
            JiraRequestSlot.slot_number == slot.slot_number,
            JiraRequestSlot.fence == old_fence,
            or_(JiraRequestSlot.owner_token.is_(None), JiraRequestSlot.lease_until < now),
        ).update(
            {
                JiraRequestSlot.owner_token: owner,
                JiraRequestSlot.lease_until: lease_until,
                JiraRequestSlot.fence: old_fence + 1,
            },
            synchronize_session=False,
        )
        db.session.commit()
        if updated == 1:
            return slot.slot_number, old_fence + 1
    return None


def _release_request_slot(job: BackgroundJob, owner: str, slot: tuple[int, int]) -> None:
    scope = db.session.get(JiraScope, job.scope_id)
    if scope is None:
        return
    slot_number, fence = slot
    JiraRequestSlot.query.filter_by(
        source_id=scope.source_id,
        slot_number=slot_number,
        owner_token=owner,
        fence=fence,
    ).update(
        {JiraRequestSlot.owner_token: None, JiraRequestSlot.lease_until: None},
        synchronize_session=False,
    )
    db.session.commit()


def _current_job(job_id: str, owner: str, fence: int, epoch: int) -> BackgroundJob:
    job = BackgroundJob.query.filter_by(
        id=job_id,
        state="running",
        lease_owner=owner,
        fence=fence,
        leader_epoch=epoch,
    ).first()
    if job is None or _aware(job.lease_until) < now_utc():
        raise LeaseLost("Job lease was lost")
    leader = WorkerLeader.query.filter_by(name="sprint-worker", owner=owner, epoch=epoch).first()
    if leader is None or _aware(leader.lease_until) < now_utc():
        raise LeaseLost("Worker leadership was lost")
    return job


def _context(job: BackgroundJob) -> tuple[JiraScope, User, SprintSnapshot, str]:
    scope = db.session.get(JiraScope, job.scope_id)
    snapshot = db.session.get(SprintSnapshot, job.snapshot_id)
    user = db.session.get(User, scope.user_id) if scope else None
    if (
        not scope or not snapshot or not user or not user.is_active
        or scope.revoked_at is not None or snapshot.invalidated_at is not None
        or user.jira_credential_epoch != scope.credential_epoch
        or user.access_epoch != scope.access_epoch
    ):
        raise LeaseLost("Snapshot scope was revoked")
    if not user.jira_pat_enc:
        raise SprintViewerServiceError("Jira credential is unavailable")
    pat = CryptoService(current_app.config["FERNET_KEY"]).decrypt(user.jira_pat_enc)
    return scope, user, snapshot, pat


def _new_revision(component: SprintComponent, job: BackgroundJob, fence: int) -> SprintComponentRevision:
    revision = SprintComponentRevision(
        component_id=component.id,
        revision=component.next_revision,
        state="staging",
        producer_job_id=job.id,
        producer_fence=fence,
    )
    component.next_revision += 1
    component.state = "running"
    db.session.add(revision)
    db.session.commit()
    return revision


def _publish(
    job_id: str,
    owner: str,
    fence: int,
    epoch: int,
    revision_id: int,
    output: dict[str, Any],
    *,
    quality: str = "verified",
    commit: bool = True,
) -> None:
    job = _current_job(job_id, owner, fence, epoch)
    scope, user, snapshot, _pat = _context(job)
    revision = db.session.get(SprintComponentRevision, revision_id)
    component = db.session.get(SprintComponent, revision.component_id) if revision else None
    if not revision or not component or revision.producer_job_id != job.id or revision.producer_fence != fence:
        raise LeaseLost("Staging revision no longer belongs to the job")
    revision.state = "ready"
    revision.output = output
    revision.data_quality = quality
    revision.completed_at = now_utc()
    component.state = "ready"
    component.error_code = None
    component.published_revision_id = revision.id
    snapshot.response_revision += 1
    job.state = "succeeded"
    job.lease_until = None
    if commit:
        db.session.commit()


def _unavailable(job: BackgroundJob, owner: str, fence: int, epoch: int, code: str) -> None:
    current = _current_job(job.id, owner, fence, epoch)
    component = SprintComponent.query.filter_by(
        snapshot_id=current.snapshot_id, component_key=current.component_key
    ).first()
    if component:
        component.state = "unavailable"
        component.error_code = code
        snapshot = db.session.get(SprintSnapshot, current.snapshot_id)
        snapshot.response_revision += 1
    current.state = "succeeded"
    current.error_code = code
    db.session.commit()
    _maybe_activate_snapshot(current.snapshot_id)


def _fail(job: BackgroundJob, owner: str, fence: int, epoch: int, code: str, *, retryable: bool) -> None:
    try:
        current = _current_job(job.id, owner, fence, epoch)
    except LeaseLost:
        db.session.rollback()
        return
    component = SprintComponent.query.filter_by(
        snapshot_id=current.snapshot_id, component_key=current.component_key
    ).first() if current.component_key else None
    if retryable and current.attempts < current.max_attempts:
        current.state = "retry_wait"
        current.resume_kind = "restart"
        current.available_at = now_utc() + timedelta(seconds=min(30, 2 ** current.attempts))
        if component:
            component.state = "queued"
    else:
        current.state = "failed"
        if component:
            component.state = "failed"
            component.error_code = code
            snapshot = db.session.get(SprintSnapshot, current.snapshot_id)
            snapshot.response_revision += 1
    current.error_code = code
    current.lease_until = None
    db.session.commit()


def run_job(job: BackgroundJob, owner: str, epoch: int) -> None:
    fence = job.fence
    requires_jira = job.job_type != "sprint_metrics_final"
    slot = _acquire_request_slot(job, owner) if requires_jira else None
    if requires_jira and slot is None:
        job.state = "retry_wait"
        job.resume_kind = "continuation"
        job.available_at = now_utc() + timedelta(seconds=1)
        job.lease_until = None
        db.session.commit()
        return
    try:
        if job.job_type == "sprint_core":
            _run_core(job, owner, fence, epoch)
        elif job.job_type == "sprint_history":
            _run_history(job, owner, fence, epoch)
        elif job.job_type == "sprint_comments":
            _run_comments(job, owner, fence, epoch)
        elif job.job_type == "sprint_metric":
            _run_metric(job, owner, fence, epoch)
        elif job.job_type == "sprint_metrics_final":
            _run_metrics_final(job, owner, fence, epoch)
        elif job.job_type == "authorize_view":
            _run_authorize_view(job, owner, fence, epoch)
        else:
            _fail(job, owner, fence, epoch, "UNKNOWN_JOB_TYPE", retryable=False)
    except LeaseLost:
        db.session.rollback()
    except (ExternalServiceError, SprintViewerServiceError) as exc:
        db.session.rollback()
        retryable = getattr(exc, "retryable", False) or getattr(exc, "status_code", None) in {429, 502, 503, 504}
        _fail(job, owner, fence, epoch, "JIRA_TRANSIENT" if retryable else "JIRA_COMPONENT_FAILED", retryable=retryable)
    except Exception:
        log.exception("Sprint worker job failed", extra={"job_id": job.id, "job_type": job.job_type})
        db.session.rollback()
        _fail(job, owner, fence, epoch, "INTERNAL_JOB_ERROR", retryable=False)
    finally:
        if slot is not None:
            _release_request_slot(job, owner, slot)


def _run_core(job: BackgroundJob, owner: str, fence: int, epoch: int) -> None:
    scope, _user, snapshot, pat = _context(job)
    snapshot_id = snapshot.id
    scope_id = scope.id
    series = db.session.get(SprintSnapshotSeries, snapshot.series_id)
    sprint_id = series.sprint_id
    sprint_meta = dict(snapshot.sprint_metadata or {})
    request_id = job.request_id
    db.session.commit()
    service = sprint_viewer_service()
    raw = service.fetch_all_issues_for_sprint(sprint_id, pat)
    current = _current_job(job.id, owner, fence, epoch)
    scope, _user, snapshot, _pat = _context(current)
    resolver = service.build_identity_resolver(raw["issues"])
    extracted = [
        service.extract_issue_fields(item, sprint_meta.get("complete_date"), resolver)
        for item in raw["issues"]
    ]
    standard = [item for item in extracted if not item.get("is_subtask")]
    persisted_principals = _persist_principals(scope, extracted)
    for issue in extracted:
        issue["comment_total"] = None
        issue["comments"] = []
        issue["relevant_comment_count"] = None
    output = {
        "total": len(extracted),
        "standard_total": len(standard),
        "total_sp": round(service.sum_story_points(standard), 2),
        "groups": service.group_issues_by_assignee(extracted),
        "stats": service.compute_issue_quality_stats(standard),
        "sprint": sprint_meta,
        "work_type_mix": service.compute_work_type_mix(standard),
        "historical_fallback_count": len(extracted),
        "field_availability": {"history": "pending", "comments": "pending"},
        "time_basis": {"tickets": "current Jira value; historical value pending"},
        "fetched_at": now_utc().isoformat(),
    }
    component = SprintComponent.query.filter_by(snapshot_id=snapshot_id, component_key="core").one()
    revision = _new_revision(component, job, fence)
    for issue in extracted:
        db.session.add(SprintIssueRow(
            core_revision_id=revision.id,
            jira_issue_id=str(issue.get("issue_id")),
            issue_key=issue.get("issue_key"),
            principal_id=persisted_principals.get(str(issue.get("principal_id") or "unassigned")),
            payload=issue,
        ))
    revision.expected_count = raw["total"]
    revision.received_count = len(raw["issues"])
    revision.unique_count = len(extracted)
    db.session.commit()
    _publish(job.id, owner, fence, epoch, revision.id, output, quality="provisional", commit=False)
    for key, job_type, priority in (
        ("history", "sprint_history", 20),
        ("comments", "sprint_comments", 30),
    ):
        enqueue_job(scope_id, job_type=job_type, snapshot_id=snapshot_id, component_key=key,
                    lane="enrichment", priority=priority, dedupe_suffix=key, request_id=request_id)
    for index, key in enumerate(METRIC_CATEGORIES):
        queued = enqueue_job(scope_id, job_type="sprint_metric", snapshot_id=snapshot_id,
                             component_key=key, lane="enrichment", priority=40 + index,
                             dedupe_suffix=f"metric:{key}", request_id=request_id)
        queued.cursor = {"category": key}
    db.session.commit()


def _core_rows(snapshot_id: str) -> tuple[SprintComponentRevision, list[SprintIssueRow]]:
    _component_row, revision = published_output(snapshot_id, "core")
    return revision, SprintIssueRow.query.filter_by(core_revision_id=revision.id).order_by(SprintIssueRow.jira_issue_id).all()


def _run_history(job: BackgroundJob, owner: str, fence: int, epoch: int) -> None:
    _scope, _user, snapshot, pat = _context(job)
    service = sprint_viewer_service()
    _core_revision, core_rows = _core_rows(snapshot.id)
    snapshot_id = snapshot.id
    complete_date = (snapshot.sprint_metadata or {}).get("complete_date")
    materialized_rows = [
        (row.jira_issue_id, row.issue_key, dict(row.payload or {})) for row in core_rows
    ]
    db.session.commit()
    historical: dict[str, dict[str, Any]] = {}
    resolver = service.build_identity_resolver([])
    for _jira_issue_id, _issue_key, current in materialized_rows:
        resolver.seed(
            str(current.get("principal_id") or ""),
            current.get("assignee_eid"),
        )
    staged_rows: list[tuple[str, dict[str, Any]]] = []
    for jira_issue_id, issue_key, _current in materialized_rows:
        if not issue_key:
            continue
        payload = service._client.get_json(
            f"/rest/api/2/issue/{issue_key}",
            headers=service._headers(pat),
            params={"fields": f"summary,{service.story_points_field},{service.application_field},{service.epic_link_field},issuetype,status,assignee,parent,project,updated", "expand": "changelog"},
        )
        payload = service.normalize_configured_fields(payload)
        changelog = payload.get("changelog") or {}
        histories = changelog.get("histories")
        total = changelog.get("total")
        if histories is None or (isinstance(total, int) and total > len(histories)):
            _unavailable(job, owner, fence, epoch, "HISTORY_PAGINATION_UNSUPPORTED")
            return
        extracted = service.extract_issue_fields(
            payload,
            complete_date,
            resolver,
        )
        historical[jira_issue_id] = extracted
        staged_rows.append((jira_issue_id, extracted))
    current = _current_job(job.id, owner, fence, epoch)
    _scope, _user, snapshot, _pat = _context(current)
    component = SprintComponent.query.filter_by(snapshot_id=snapshot_id, component_key="history").one()
    revision = _new_revision(component, current, fence)
    for jira_issue_id, extracted in staged_rows:
        db.session.add(SprintHistoryRow(
            history_revision_id=revision.id,
            jira_issue_id=jira_issue_id,
            payload=extracted,
        ))
    revision.received_count = len(historical)
    revision.unique_count = len(historical)
    db.session.commit()
    _publish(current.id, owner, fence, epoch, revision.id, {
        "issues": historical,
        "time_basis": "at sprint completion",
        "fetched_at": now_utc().isoformat(),
    }, commit=False)
    _maybe_activate_snapshot(snapshot_id)
    db.session.commit()


def _run_comments(job: BackgroundJob, owner: str, fence: int, epoch: int) -> None:
    _scope, _user, snapshot, pat = _context(job)
    history_component = SprintComponent.query.filter_by(
        snapshot_id=snapshot.id, component_key="history"
    ).one()
    if history_component.state in {"missing", "queued", "running"}:
        current = _current_job(job.id, owner, fence, epoch)
        current.state = "retry_wait"
        current.resume_kind = "continuation"
        current.available_at = now_utc() + timedelta(seconds=1)
        current.lease_until = None
        db.session.commit()
        return
    if history_component.state != "ready":
        _unavailable(job, owner, fence, epoch, "HISTORY_IDENTITY_UNAVAILABLE")
        return
    service = sprint_viewer_service()
    _core_revision, core_rows = _core_rows(snapshot.id)
    _history_component, history_revision = published_output(snapshot.id, "history")
    historical_issues = (history_revision.output or {}).get("issues") or {}
    snapshot_id = snapshot.id
    complete_date = (snapshot.sprint_metadata or {}).get("complete_date")
    materialized_rows = [
        (row.jira_issue_id, row.issue_key, dict(row.payload or {})) for row in core_rows
    ]
    output: dict[str, Any] = {"issues": {}, "time_basis": "visible comments at collection, cutoff at sprint completion", "fetched_at": now_utc().isoformat()}
    cutoff = service._parse_jira_datetime(complete_date)
    team: set[str] = set()
    for jira_issue_id, _issue_key, payload in materialized_rows:
        identity = historical_issues.get(jira_issue_id) or payload
        principal = str(identity.get("principal_id") or "").strip()
        eid = str(identity.get("assignee_eid") or "").strip()
        team.update(value for value in (principal, eid, principal.partition(":")[2]) if value)
    db.session.commit()
    staged_comments: list[tuple[str, str, Any]] = []
    for jira_issue_id, issue_key, _payload in materialized_rows:
        if not issue_key:
            continue
        comments = service._fetch_all_comments_for_issue(issue_key, pat)
        relevant = 0
        ids: list[str] = []
        for comment in comments:
            comment_id = str(comment.get("id") or "")
            if not comment_id:
                continue
            author = comment.get("author") or {}
            author_values = {
                str(author.get(field) or "").strip()
                for field in ("accountId", "key", "name")
            }
            author_values.discard("")
            created = service._parse_jira_datetime(comment.get("created"))
            if author_values.intersection(team) and (cutoff is None or (created is not None and created <= cutoff)):
                relevant += 1
                ids.append(comment_id)
                staged_comments.append((jira_issue_id, comment_id, comment.get("created")))
        output["issues"][jira_issue_id] = {
            "comment_total": len(comments),
            "relevant_comment_count": relevant,
            "visible_ids": ids,
        }
    enriched = []
    for jira_issue_id, _issue_key, payload in materialized_rows:
        issue = dict(payload)
        issue.update(output["issues"].get(jira_issue_id) or {})
        enriched.append(issue)
    output["stats"] = service.compute_issue_quality_stats(
        [issue for issue in enriched if not issue.get("is_subtask")]
    )
    current = _current_job(job.id, owner, fence, epoch)
    _scope, _user, snapshot, _pat = _context(current)
    component = SprintComponent.query.filter_by(snapshot_id=snapshot_id, component_key="comments").one()
    revision = _new_revision(component, current, fence)
    for jira_issue_id, comment_id, created in staged_comments:
        db.session.add(SprintCommentRow(
            comments_revision_id=revision.id,
            jira_issue_id=jira_issue_id,
            jira_comment_id=comment_id,
            created_at_source=created,
        ))
    revision.received_count = len(materialized_rows)
    revision.unique_count = len(materialized_rows)
    db.session.commit()
    _publish(job.id, owner, fence, epoch, revision.id, output, commit=False)
    _maybe_activate_snapshot(snapshot_id)
    db.session.commit()


def _run_metric(job: BackgroundJob, owner: str, fence: int, epoch: int) -> None:
    scope, _user, snapshot, pat = _context(job)
    series = db.session.get(SprintSnapshotSeries, snapshot.series_id)
    category = str((job.cursor or {}).get("category") or job.component_key)
    spec = metric_queries(series.board_id, series.sprint_id)[category]
    snapshot_id = snapshot.id
    scope_id = scope.id
    request_id = job.request_id
    db.session.commit()
    service = sprint_viewer_service()
    result = service._aggregate_by_jql_with_client(service._client, spec["jql"], pat, spec["capture_keys"])
    current = _current_job(job.id, owner, fence, epoch)
    _scope, _user, snapshot, _pat = _context(current)
    component = SprintComponent.query.filter_by(snapshot_id=snapshot_id, component_key=category).one()
    revision = _new_revision(component, current, fence)
    for membership in result.get("memberships") or []:
        db.session.add(SprintMetricMembership(
            category_revision_id=revision.id,
            jira_issue_id=membership["issue_id"],
            issue_key=membership.get("issue_key"),
            project_id=membership.get("project_id"),
            project_key=membership.get("project_key"),
            story_points=membership.get("story_points"),
            source_updated_at=membership.get("updated"),
        ))
    revision.received_count = result["count"]
    revision.unique_count = result["count"]
    db.session.commit()
    _publish(job.id, owner, fence, epoch, revision.id, result, commit=False)
    states = component_map(snapshot_id)
    if all(states[key].state == "ready" for key in METRIC_CATEGORIES):
        enqueue_job(scope_id, job_type="sprint_metrics_final", snapshot_id=snapshot_id,
                    component_key="metrics", lane="enrichment", priority=80,
                    dedupe_suffix="metrics-final", request_id=request_id)
    db.session.commit()


def _run_metrics_final(job: BackgroundJob, owner: str, fence: int, epoch: int) -> None:
    _scope, _user, snapshot, _pat = _context(job)
    results = {key: published_output(snapshot.id, key)[1].output for key in METRIC_CATEGORIES}
    metrics = build_scrum_metrics(results)
    metrics["fetched_at"] = now_utc().isoformat()
    component = SprintComponent.query.filter_by(snapshot_id=snapshot.id, component_key="metrics").one()
    revision = _new_revision(component, job, fence)
    revision.input_revisions = {
        key: component_map(snapshot.id)[key].published_revision_id for key in METRIC_CATEGORIES
    }
    db.session.commit()
    _publish(job.id, owner, fence, epoch, revision.id, metrics, commit=False)
    _maybe_activate_snapshot(snapshot.id)
    db.session.commit()


def _verify_board_sprint(service, board_id: int, sprint_id: int, pat: str) -> bool:
    def fetch(start: int, page_size: int):
        return service._client.get_json(
            f"/rest/agile/1.0/board/{board_id}/sprint",
            headers=service._headers(pat),
            params={"startAt": start, "maxResults": page_size, "state": "closed"},
        )
    sprints = collect_offset_pages(fetch, collection_key="values", requested_page_size=50,
                                   identity=lambda item: str(item.get("id")) if item.get("id") is not None else None)
    return str(sprint_id) in {str(item.get("id")) for item in sprints}


def _visible_issue_ids(service, pat: str, issue_ids: set[str]) -> set[str]:
    visible: set[str] = set()
    ordered = sorted(issue_ids, key=lambda value: (len(value), value))
    for offset in range(0, len(ordered), 500):
        batch = ordered[offset:offset + 500]
        if not batch:
            continue
        jql = "id in (" + ",".join(batch) + ") ORDER BY id ASC"
        result = service._aggregate_by_jql_with_client(service._client, jql, pat, False)
        visible.update(item["issue_id"] for item in result.get("memberships") or [])
    return visible


def _comments_still_visible(service, pat: str, snapshot_id: str) -> bool:
    """Verify every stored comment against the caller's current Jira view."""
    _revision, output = published_output(snapshot_id, "comments")
    stored_by_issue = (output or {}).get("issues") or {}
    _core_revision, core_rows = _core_rows(snapshot_id)
    materialized = [
        (
            row.jira_issue_id,
            row.issue_key,
            {
                str(value)
                for value in (stored_by_issue.get(row.jira_issue_id) or {}).get("visible_ids", [])
            },
        )
        for row in core_rows
    ]
    db.session.commit()
    for _jira_issue_id, issue_key, stored_ids in materialized:
        if not stored_ids or not issue_key:
            continue
        current_ids = {
            str(comment.get("id"))
            for comment in service._fetch_all_comments_for_issue(issue_key, pat)
            if comment.get("id") is not None
        }
        if not stored_ids.issubset(current_ids):
            return False
    return True


def _run_authorize_view(job: BackgroundJob, owner: str, fence: int, epoch: int) -> None:
    _scope, user, snapshot, pat = _context(job)
    view_id = str((job.cursor or {}).get("view_id") or "")
    snapshot_id, user_id = snapshot.id, user.id
    view = ReportView.query.filter_by(
        id=view_id, user_id=user_id, snapshot_id=snapshot_id, revoked_at=None
    ).first()
    if not view:
        raise LeaseLost("Report view is gone")
    components = component_map(snapshot_id)
    if components["core"].state != "ready":
        job.state = "retry_wait"
        job.resume_kind = "continuation"
        job.available_at = now_utc() + timedelta(seconds=1)
        job.lease_until = None
        db.session.commit()
        return

    series = db.session.get(SprintSnapshotSeries, snapshot.series_id)
    expected_eid, expected_key = user.eid, user.jira_key
    board_id, sprint_id = series.board_id, series.sprint_id
    component_states = {key: value.state for key, value in components.items()}
    component_revisions = {key: value.published_revision_id for key, value in components.items()}
    prior_access = dict(view.access_state or {})
    prior_verified = dict(view.verified_revisions or {})
    core_ids = {row.jira_issue_id for row in _core_rows(snapshot_id)[1]}
    metric_ready = all(component_states[key] == "ready" for key in METRIC_CATEGORIES)
    metric_ids: set[str] = set()
    if metric_ready:
        revision_ids = [component_revisions[key] for key in METRIC_CATEGORIES]
        metric_ids = {
            value for (value,) in db.session.query(SprintMetricMembership.jira_issue_id)
            .filter(SprintMetricMembership.category_revision_id.in_(revision_ids)).all()
        }
    reuse_core_grant = (
        prior_access.get("base") == "granted"
        and prior_access.get("core") == "granted"
        and prior_verified.get("core") == component_revisions["core"]
    )
    reuse_metric_grant = metric_ready and prior_access.get("metrics") == "granted" and all(
        prior_verified.get(key) == component_revisions[key] for key in METRIC_CATEGORIES
    )
    reuse_comment_grant = (
        component_states["comments"] == "ready"
        and prior_access.get("comments") == "granted"
        and prior_verified.get("comments") == component_revisions["comments"]
    )
    db.session.commit()

    service = sprint_viewer_service()
    base_granted = reuse_core_grant
    core_granted = reuse_core_grant
    denial_code = None
    if not reuse_core_grant:
        profile = jira_service().fetch_myself(pat)
        profile_eid = str(profile.get("name") or "").strip()
        profile_key = str(profile.get("key") or "").strip()
        base_granted = bool(
            profile.get("active")
            and not profile.get("deleted")
            and (profile_eid == expected_eid or profile_key == expected_key)
        )
        if not base_granted:
            denial_code = "JIRA_ACCESS_DENIED"
        elif not _verify_board_sprint(service, board_id, sprint_id, pat):
            denial_code = "REPORT_ACCESS_CHANGED"
        else:
            core_granted = _visible_issue_ids(service, pat, core_ids) == core_ids
            if not core_granted:
                denial_code = "REPORT_ACCESS_CHANGED"

    metrics_granted = False
    if core_granted and metric_ready:
        metrics_granted = reuse_metric_grant or _visible_issue_ids(service, pat, metric_ids) == metric_ids
        if not metrics_granted:
            denial_code = "METRIC_ACCESS_CHANGED"

    optional_terminal = all(
        component_states[key] in {"ready", "unavailable", "failed"}
        for key in ("history", "comments")
    )
    comments_state = "pending"
    if component_states["comments"] == "ready" and core_granted:
        comments_state = "granted" if (
            reuse_comment_grant or _comments_still_visible(service, pat, snapshot_id)
        ) else "denied"
    elif component_states["comments"] in {"unavailable", "failed"}:
        comments_state = "unavailable"
    history_state = (
        "granted"
        if component_states["history"] == "ready"
        and current_app.config.get("JIRA_HISTORY_VISIBILITY_FOLLOWS_ISSUE", False)
        and core_granted
        else (
            "pending" if component_states["history"] not in {"ready", "unavailable", "failed"}
            else "unavailable"
        )
    )

    current = _current_job(job.id, owner, fence, epoch)
    _scope, _user, _snapshot, _pat = _context(current)
    view = ReportView.query.filter_by(
        id=view_id, user_id=user_id, snapshot_id=snapshot_id, revoked_at=None
    ).first()
    if not view:
        raise LeaseLost("Report view is gone")
    latest_components = component_map(snapshot_id)
    view.access_state = {
        "base": "granted" if base_granted else "denied",
        "core": "granted" if core_granted else "denied",
        "metrics": (
            "denied" if not core_granted
            else "granted" if metrics_granted
            else "pending" if not metric_ready
            else "denied"
        ),
        "comments": comments_state if core_granted else "denied",
        "history": history_state if core_granted else "denied",
    }
    view.verified_revisions = {
        key: component.published_revision_id
        for key, component in latest_components.items()
        if component.published_revision_id and view.access_state.get(
            "metrics" if key in METRIC_CATEGORIES or key == "metrics" else key
        ) == "granted"
    }
    view.expires_at = now_utc() + timedelta(seconds=300)
    view.error_code = denial_code
    if denial_code or (metric_ready and not metrics_granted):
        current.state = "succeeded"
        current.lease_until = None
    elif not metric_ready or not optional_terminal:
        current.state = "retry_wait"
        current.resume_kind = "continuation"
        current.available_at = now_utc() + timedelta(seconds=1)
        current.lease_until = None
    else:
        current.state = "succeeded"
        current.lease_until = None
    db.session.commit()


def _maybe_activate_snapshot(snapshot_id: str) -> None:
    snapshot = db.session.get(SprintSnapshot, snapshot_id)
    if not snapshot or snapshot.invalidated_at is not None:
        return
    components = component_map(snapshot_id)
    required_ready = all(components[key].state == "ready" for key in ("core", *METRIC_CATEGORIES, "metrics"))
    optional_terminal = all(components[key].state in {"ready", "unavailable"} for key in ("history", "comments"))
    if required_ready and optional_terminal:
        series = db.session.get(SprintSnapshotSeries, snapshot.series_id)
        snapshot.status = "ready"
        snapshot.collection_ended_at = now_utc()
        snapshot.response_revision += 1
        series.active_snapshot_id = snapshot.id
        if series.candidate_snapshot_id == snapshot.id:
            series.candidate_snapshot_id = None
        db.session.commit()
