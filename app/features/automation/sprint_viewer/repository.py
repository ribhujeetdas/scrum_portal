from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Any

from flask import current_app, session
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from ....extensions import db
from ....models import User, UserBoard, UserBoardSprint, UserProject
from .calculations import METRIC_CATEGORIES
from .models import (
    BackgroundJob,
    JiraScope,
    JiraRequestSlot,
    JiraSource,
    ReportView,
    SprintComponent,
    SprintComponentRevision,
    SprintIssueRow,
    SprintSnapshot,
    SprintSnapshotSeries,
)


class SnapshotNotFound(LookupError):
    pass


class SnapshotAccessDenied(PermissionError):
    pass


def now_utc() -> datetime:
    return datetime.now(UTC)


def ensure_source() -> JiraSource:
    source_key = str(current_app.config["JIRA_SOURCE_ID"])
    base_url = str(current_app.config["JIRA_BASE_URL"]).rstrip("/")
    fingerprint = hashlib.sha256(base_url.encode("utf-8")).hexdigest()
    source = JiraSource.query.filter_by(source_key=source_key).first()
    if source is None:
        source = JiraSource(
            source_key=source_key,
            base_url=base_url,
            config_fingerprint=fingerprint,
            enabled=True,
        )
        db.session.add(source)
        db.session.flush()
    elif source.config_fingerprint != fingerprint or source.base_url != base_url:
        raise RuntimeError("JIRA_SOURCE_ID already belongs to a different Jira base URL")
    if not source.enabled:
        raise SnapshotAccessDenied("Jira source is disabled")
    existing_slots = {
        slot.slot_number: slot
        for slot in JiraRequestSlot.query.filter_by(source_id=source.id).all()
    }
    total_slots = max(2, int(current_app.config.get("JIRA_MAX_INFLIGHT_PER_SOURCE", 4)))
    background_slots = max(
        1,
        min(
            total_slots - 1,
            int(current_app.config.get("JIRA_MAX_BACKGROUND_INFLIGHT", 2)),
        ),
    )
    interactive_slots = total_slots - background_slots
    for slot_number in range(1, total_slots + 1):
        slot_class = "interactive" if slot_number <= interactive_slots else "background"
        if slot_number not in existing_slots:
            db.session.add(JiraRequestSlot(
                source_id=source.id,
                slot_number=slot_number,
                slot_class=slot_class,
            ))
        else:
            existing_slots[slot_number].slot_class = slot_class
    return source


def current_scope(user: User) -> JiraScope:
    source = ensure_source()
    scope = JiraScope.query.filter_by(
        user_id=user.id,
        source_id=source.id,
        credential_epoch=user.jira_credential_epoch,
        access_epoch=user.access_epoch,
        revoked_at=None,
    ).first()
    if scope is None:
        scope = JiraScope(
            user_id=user.id,
            source_id=source.id,
            credential_epoch=user.jira_credential_epoch,
            access_epoch=user.access_epoch,
        )
        db.session.add(scope)
        db.session.flush()
    return scope


def require_selection(user_id: int, board_id: int, sprint_id: int) -> tuple[UserBoard, UserBoardSprint]:
    board = (
        UserBoard.query.join(UserProject, UserBoard.project_id == UserProject.id)
        .filter(UserProject.user_id == user_id, UserBoard.board_id == board_id)
        .first()
    )
    if board is None:
        raise SnapshotAccessDenied("Selected board is not saved for this user")
    sprint = UserBoardSprint.query.filter_by(
        user_id=user_id, board_id=board_id, sprint_id=sprint_id
    ).first()
    if sprint is None:
        raise SnapshotNotFound("Selected sprint is not in the saved board catalog")
    return board, sprint


def _component(snapshot_id: str, key: str) -> SprintComponent:
    component = SprintComponent.query.filter_by(snapshot_id=snapshot_id, component_key=key).first()
    if component is None:
        component = SprintComponent(snapshot_id=snapshot_id, component_key=key, state="missing")
        db.session.add(component)
        db.session.flush()
    return component


def _active_job(dedupe_key: str) -> BackgroundJob | None:
    return BackgroundJob.query.filter(
        BackgroundJob.dedupe_key == dedupe_key,
        BackgroundJob.state.in_(("queued", "running", "retry_wait")),
    ).first()


def enqueue_job(
    scope_id: str,
    *,
    job_type: str,
    snapshot_id: str,
    component_key: str | None,
    lane: str,
    priority: int,
    dedupe_suffix: str,
    request_id: str | None = None,
) -> BackgroundJob:
    dedupe_key = f"{scope_id}:{snapshot_id}:{dedupe_suffix}"
    existing = _active_job(dedupe_key)
    if existing:
        return existing
    job = BackgroundJob(
        job_type=job_type,
        scope_id=scope_id,
        snapshot_id=snapshot_id,
        component_key=component_key,
        dedupe_key=dedupe_key,
        lane=lane,
        priority=priority,
        max_attempts=int(current_app.config.get("SPRINT_JOB_MAX_ATTEMPTS", 3)),
        request_id=request_id,
    )
    db.session.add(job)
    if component_key:
        component = _component(snapshot_id, component_key)
        if component.state in {"missing", "failed", "unavailable"}:
            component.state = "queued"
            component.error_code = None
    db.session.flush()
    return job


def _create_candidate(
    scope: JiraScope,
    series: SprintSnapshotSeries,
    sprint: UserBoardSprint,
    *,
    request_id: str | None = None,
) -> SprintSnapshot:
    active_for_user = (
        SprintSnapshot.query
        .join(SprintSnapshotSeries, SprintSnapshot.series_id == SprintSnapshotSeries.id)
        .join(JiraScope, SprintSnapshotSeries.scope_id == JiraScope.id)
        .filter(
            JiraScope.user_id == scope.user_id,
            JiraScope.revoked_at.is_(None),
            SprintSnapshot.status == "processing",
            SprintSnapshot.invalidated_at.is_(None),
        )
        .count()
    )
    if active_for_user >= 3:
        raise SnapshotAccessDenied("Three sprint imports are already in progress for this user")
    next_generation = db.session.execute(
        update(SprintSnapshotSeries)
        .where(SprintSnapshotSeries.id == series.id)
        .values(next_generation=SprintSnapshotSeries.next_generation + 1)
        .returning(SprintSnapshotSeries.next_generation)
    ).scalar_one()
    generation = int(next_generation) - 1
    series.next_generation = int(next_generation)
    candidate = SprintSnapshot(
        series_id=series.id,
        generation=generation,
        sprint_metadata={
            "id": sprint.sprint_id,
            "name": sprint.sprint_name,
            "state": sprint.sprint_state,
            "start_date": sprint.start_date,
            "end_date": sprint.end_date,
            "activated_date": sprint.activated_date,
            "complete_date": sprint.complete_date,
            "goal": sprint.goal,
        },
        collection_started_at=now_utc(),
    )
    db.session.add(candidate)
    db.session.flush()
    series.candidate_snapshot_id = candidate.id
    for key in ("core", "history", "comments", *METRIC_CATEGORIES, "metrics"):
        db.session.add(SprintComponent(snapshot_id=candidate.id, component_key=key))
    db.session.flush()
    enqueue_job(
        scope.id,
        job_type="sprint_core",
        snapshot_id=candidate.id,
        component_key="core",
        lane="core",
        priority=10,
        dedupe_suffix="core",
        request_id=request_id,
    )
    return candidate


def get_or_create_snapshot(
    user: User,
    board_id: int,
    sprint_id: int,
    *,
    request_id: str | None = None,
) -> tuple[JiraScope, SprintSnapshot, bool]:
    _board, sprint = require_selection(user.id, board_id, sprint_id)
    scope = current_scope(user)
    versions = (1, 1, 1)
    series = SprintSnapshotSeries.query.filter_by(
        scope_id=scope.id,
        board_id=board_id,
        sprint_id=sprint_id,
        schema_version=versions[0],
        query_version=versions[1],
        calculation_version=versions[2],
    ).first()
    if series is None:
        series = SprintSnapshotSeries(
            scope_id=scope.id,
            board_id=board_id,
            sprint_id=sprint_id,
            schema_version=1,
            query_version=1,
            calculation_version=1,
        )
        db.session.add(series)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            scope = current_scope(user)
            series = SprintSnapshotSeries.query.filter_by(
                scope_id=scope.id, board_id=board_id, sprint_id=sprint_id,
                schema_version=1, query_version=1, calculation_version=1,
            ).one()
    if series.active_snapshot_id:
        active = db.session.get(SprintSnapshot, series.active_snapshot_id)
        if active and active.invalidated_at is None and active.status == "ready":
            return scope, active, False
    candidate = db.session.get(SprintSnapshot, series.candidate_snapshot_id) if series.candidate_snapshot_id else None
    created = False
    if candidate is None or candidate.invalidated_at is not None:
        candidate = _create_candidate(scope, series, sprint, request_id=request_id)
        created = True
    return scope, candidate, created


def queue_snapshot_rebuild(
    user: User,
    board_id: int,
    sprint_id: int,
    *,
    request_id: str | None = None,
) -> tuple[JiraScope, SprintSnapshot, bool]:
    """Queue an explicit replacement generation while keeping the active one readable."""
    _board, sprint = require_selection(user.id, board_id, sprint_id)
    scope = current_scope(user)
    series = SprintSnapshotSeries.query.filter_by(
        scope_id=scope.id,
        board_id=board_id,
        sprint_id=sprint_id,
        schema_version=1,
        query_version=1,
        calculation_version=1,
    ).first()
    if series is None:
        _scope, snapshot, created = get_or_create_snapshot(
            user, board_id, sprint_id, request_id=request_id
        )
        return _scope, snapshot, created
    candidate = (
        db.session.get(SprintSnapshot, series.candidate_snapshot_id)
        if series.candidate_snapshot_id else None
    )
    if candidate and candidate.invalidated_at is None and candidate.status in {"pending", "processing"}:
        return scope, candidate, False
    candidate = _create_candidate(scope, series, sprint, request_id=request_id)
    return scope, candidate, True


def create_report_view(
    user: User,
    scope: JiraScope,
    snapshot: SprintSnapshot,
    client_action_id: str,
    *,
    purpose: str = "view",
    request_id: str | None = None,
) -> ReportView:
    auth_session_id = session.get("auth_session_id")
    existing = ReportView.query.filter_by(
        auth_session_id=auth_session_id,
        client_action_nonce=client_action_id,
    ).first() if auth_session_id else None
    if existing:
        if existing.snapshot_id != snapshot.id or existing.user_id != user.id:
            raise SnapshotAccessDenied("Client action ID is already bound to another report")
        return existing
    view = ReportView(
        user_id=user.id,
        auth_session_id=auth_session_id,
        scope_id=scope.id,
        snapshot_id=snapshot.id,
        client_action_nonce=client_action_id,
        purpose=purpose,
        expires_at=now_utc() + timedelta(seconds=300),
        access_state={"base": "pending", "core": "pending", "metrics": "pending", "comments": "pending", "history": "pending"},
    )
    db.session.add(view)
    db.session.flush()
    enqueue_job(
        scope.id,
        job_type="authorize_view",
        snapshot_id=snapshot.id,
        component_key=None,
        lane="core",
        priority=1,
        dedupe_suffix=f"authorize:{view.id}",
        request_id=request_id,
    ).cursor = {"view_id": view.id}
    return view


def owned_snapshot(user: User, snapshot_id: str) -> tuple[JiraScope, SprintSnapshot]:
    row = (
        db.session.query(JiraScope, SprintSnapshot)
        .join(SprintSnapshotSeries, SprintSnapshotSeries.scope_id == JiraScope.id)
        .join(SprintSnapshot, SprintSnapshot.series_id == SprintSnapshotSeries.id)
        .filter(
            SprintSnapshot.id == snapshot_id,
            JiraScope.user_id == user.id,
            JiraScope.credential_epoch == user.jira_credential_epoch,
            JiraScope.access_epoch == user.access_epoch,
            JiraScope.revoked_at.is_(None),
            SprintSnapshot.invalidated_at.is_(None),
        )
        .first()
    )
    if row is None:
        raise SnapshotNotFound("Snapshot not found")
    return row


def owned_view(user: User, snapshot_id: str, view_id: str) -> ReportView:
    view = ReportView.query.filter_by(
        id=view_id, user_id=user.id, snapshot_id=snapshot_id, revoked_at=None
    ).first()
    if view is None:
        raise SnapshotNotFound("Report view not found")
    if view.auth_session_id and view.auth_session_id != session.get("auth_session_id"):
        raise SnapshotNotFound("Report view not found")
    return view


def component_map(snapshot_id: str) -> dict[str, SprintComponent]:
    return {
        component.component_key: component
        for component in SprintComponent.query.filter_by(snapshot_id=snapshot_id).all()
    }


def serialize_status(snapshot: SprintSnapshot, view: ReportView) -> dict[str, Any]:
    components = component_map(snapshot.id)
    latest_revisions: dict[int, SprintComponentRevision] = {}
    component_ids = [component.id for component in components.values()]
    if component_ids:
        for revision in (
            SprintComponentRevision.query
            .filter(SprintComponentRevision.component_id.in_(component_ids))
            .order_by(SprintComponentRevision.component_id, SprintComponentRevision.revision.desc())
            .all()
        ):
            latest_revisions.setdefault(revision.component_id, revision)
    return {
        "state": snapshot.status,
        "source": "db",
        "snapshot_id": snapshot.id,
        "view_id": view.id,
        "generation": snapshot.generation,
        "response_revision": snapshot.response_revision,
        "retry_after_ms": 1500,
        "components": {
            key: {
                "state": value.state,
                "revision": value.published_revision_id,
                "error_code": value.error_code,
                "progress": (
                    {
                        "expected": latest_revisions[value.id].expected_count,
                        "received": latest_revisions[value.id].received_count,
                        "unique": latest_revisions[value.id].unique_count,
                    }
                    if value.id in latest_revisions else None
                ),
            }
            for key, value in components.items()
        },
        "access": dict(view.access_state or {}),
        "export_ready": export_ready(snapshot, view, components),
    }


def export_ready(snapshot: SprintSnapshot, view: ReportView, components: dict[str, SprintComponent] | None = None) -> bool:
    components = components or component_map(snapshot.id)
    required = ("core", *METRIC_CATEGORIES, "metrics")
    terminal_optional = all(components[key].state in {"ready", "unavailable"} for key in ("history", "comments"))
    access = view.access_state or {}
    return bool(
        snapshot.status == "ready"
        and terminal_optional
        and all(components[key].state == "ready" for key in required)
        and access.get("core") == "granted"
        and access.get("metrics") == "granted"
    )


def published_output(snapshot_id: str, component_key: str) -> tuple[SprintComponent, SprintComponentRevision]:
    component = SprintComponent.query.filter_by(snapshot_id=snapshot_id, component_key=component_key).first()
    if component is None or component.state != "ready" or not component.published_revision_id:
        raise SnapshotNotFound("Component is not ready")
    revision = db.session.get(SprintComponentRevision, component.published_revision_id)
    if revision is None or revision.state != "ready":
        raise SnapshotNotFound("Component revision is not ready")
    return component, revision


def core_issue_page(
    revision_id: int,
    *,
    cursor: str | None = None,
    limit: int = 200,
) -> tuple[list[dict[str, Any]], str | None]:
    query = SprintIssueRow.query.filter_by(core_revision_id=revision_id)
    if cursor:
        query = query.filter(SprintIssueRow.jira_issue_id > cursor)
    rows = query.order_by(SprintIssueRow.jira_issue_id.asc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return [dict(row.payload) for row in rows], (rows[-1].jira_issue_id if rows and has_more else None)
