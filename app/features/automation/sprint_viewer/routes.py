from __future__ import annotations

import logging
from datetime import UTC, datetime
import uuid

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import selectinload

from ....core.api import json_accepted, json_error, json_ok, safe_error_message
from ....core.dependencies import crypto_service, jira_service, sprint_viewer_service
from ....core.error_logging import log_handled_exception
from ....core.jira_pat_validation import validate_jira_pat_for_current_user
from ....core.rate_limits import consume_current_user_limit
from ....extensions import db
from ....models import UserBoard, UserBoardSprint, UserProject
from ....services.jira_service import JiraServiceError
from ....services.sprint_viewer_service import SprintViewerService, SprintViewerServiceError
from .schemas import InputValidationError, positive_jira_id, require_json_object, strict_boolean
from .calculations import METRIC_CATEGORIES
from .models import BackgroundJob, JiraSprintCatalog, ReportView, SprintComponent, SprintSnapshotSeries
from .repository import (
    SnapshotAccessDenied,
    SnapshotNotFound,
    component_map,
    core_issue_page,
    create_report_view,
    enqueue_job,
    export_ready,
    get_or_create_snapshot,
    owned_snapshot,
    owned_view,
    published_output,
    serialize_status,
    ensure_source,
)


def _sprint_service() -> SprintViewerService:
    return sprint_viewer_service()


def _trace_api(msg: str, *args) -> None:
    if current_app.config.get("TRACE_SPRINT_VIEWER_API", False):
        current_app.logger.debug(msg, *args)


def _get_user_pat() -> str:
    if not current_user.jira_pat_enc:
        raise ValueError(
            "Enterprise Agile Jira PAT is not set. Please set it in Profile."
        )
    return crypto_service().decrypt(current_user.jira_pat_enc)


def _validate_pat_belongs_to_user(pat: str) -> None:
    validate_jira_pat_for_current_user(pat, jira_service().fetch_myself)


def _board_belongs_to_user_and_project(user_id: int, project_key: str, board_id: int) -> bool:
    q = (
        UserBoard.query.join(UserProject, UserBoard.project_id == UserProject.id)
        .filter(
            UserProject.user_id == user_id,
            UserProject.project_key == project_key,
            UserBoard.board_id == board_id,
        )
        .first()
    )
    return q is not None


def _board_belongs_to_user(user_id: int, board_id: int) -> bool:
    q = (
        UserBoard.query.join(UserProject, UserBoard.project_id == UserProject.id)
        .filter(
            UserProject.user_id == user_id,
            UserBoard.board_id == board_id,
        )
        .first()
    )
    return q is not None


def _snapshot_mode() -> bool:
    if current_app.config.get("SPRINT_VIEWER_MODE") != "snapshot":
        return False
    raw = str(current_app.config.get("SPRINT_VIEWER_SNAPSHOT_USER_IDS") or "").strip()
    if not raw:
        return True
    allowed = {part.strip() for part in raw.split(",") if part.strip()}
    return str(current_user.id) in allowed


def _client_action(payload: dict) -> str:
    value = str(payload.get("client_action_id") or uuid.uuid4()).strip()
    if len(value) > 64:
        raise InputValidationError("client_action_id is too long.")
    return value


def _valid_uuid(value: str, label: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise InputValidationError(f"{label} is invalid.") from exc


def _view_access_fresh(view: ReportView) -> bool:
    expires = view.expires_at if view.expires_at.tzinfo else view.expires_at.replace(tzinfo=UTC)
    return datetime.now(UTC) <= expires


def sprint_viewer_page():
    projects = (
        UserProject.query.options(selectinload(UserProject.boards))
        .filter_by(user_id=current_user.id, admin_projects=True)
        .order_by(UserProject.project_key.asc())
        .all()
    )
    if not projects:
        flash(
            "No project key found. Redirecting you to Settings to add Projects & Boards.",
            "warning",
        )
        return redirect(url_for("aliases.settings_projects_boards"))

    boards_by_project: dict[str, list[dict]] = {}
    for project in projects:
        boards = sorted(project.boards, key=lambda board: board.board_name.casefold())
        boards_by_project[project.project_key] = [
            {
                "board_id": board.board_id,
                "board_name": board.board_name,
                "board_type": board.board_type,
                "board_url": board.board_url,
            }
            for board in boards
        ]

    return render_template(
        "automation/sprint_viewer.html",
        projects=[project.project_key for project in projects],
        boards_by_project=boards_by_project,
        jira_base_url=current_app.config["JIRA_BASE_URL"].rstrip("/"),
        trace_ui=bool(current_app.config.get("TRACE_SPRINT_VIEWER_UI", False)),
        snapshot_mode=_snapshot_mode(),
    )


def sprint_viewer_get_sprints():
    try:
        payload = require_json_object(request.get_json(silent=True))
        board_id_int = positive_jira_id(payload.get("board_id"), "Board ID")
        refresh = strict_boolean(payload.get("refresh"), "refresh")
    except InputValidationError as exc:
        return json_error(str(exc), status_code=400, code="INVALID_INPUT")
    project_key = str(payload.get("project_key") or "").strip().upper()

    if not project_key:
        return json_error("Project key is required.", status_code=400)

    if not _board_belongs_to_user_and_project(current_user.id, project_key, board_id_int):
        return json_error(
            "Selected board does not belong to selected project for this user.",
            status_code=403,
        )

    try:
        pat = _get_user_pat()
        _validate_pat_belongs_to_user(pat)
    except JiraServiceError as exc:
        log_handled_exception(
            "Sprint Viewer PAT validation failed",
            exc,
            event="automation.sprint_viewer.pat_validation_failed",
            feature="sprint_viewer",
            operation="get_sprints",
        )
        return json_error(safe_error_message("validate Jira access"), status_code=403)
    except Exception as exc:
        return json_error(str(exc), status_code=403)

    _trace_api(
        "SprintViewer/sprints request user=%s project=%s board=%s refresh=%s",
        current_user.eid,
        project_key,
        board_id_int,
        refresh,
    )

    existing = (
        UserBoardSprint.query.filter_by(user_id=current_user.id, board_id=board_id_int)
        .order_by(UserBoardSprint.sprint_id.desc())
        .all()
    )
    source = ensure_source()
    catalog = JiraSprintCatalog.query.filter_by(
        user_id=current_user.id,
        source_id=source.id,
        board_id=board_id_int,
        state="complete",
    ).first()

    if catalog is not None and not refresh:
        return json_ok(
            source="db",
            sprints=[
                {"id": s.sprint_id, "name": s.sprint_name, "state": s.sprint_state}
                for s in existing
            ],
        )

    try:
        sprints = _sprint_service().fetch_closed_sprints_for_board(board_id_int, pat)
    except SprintViewerServiceError as exc:
        log_handled_exception(
            "Sprint Viewer failed to fetch sprints",
            exc,
            event="automation.sprint_viewer.sprints_failed",
            feature="sprint_viewer",
            operation="get_sprints",
            context={"board_id": board_id_int, "project_key": project_key},
        )
        return json_error(safe_error_message("load sprints"), status_code=400)

    try:
        # Jira work completed before this transaction. Reconciliation is atomic,
        # so a failed refresh never erases the last successful catalog.
        incoming_ids = {int(sprint.get("id")) for sprint in sprints}
        current_rows = UserBoardSprint.query.filter_by(
            user_id=current_user.id, board_id=board_id_int
        ).all()
        current_by_id = {row.sprint_id: row for row in current_rows}
        for removed_id in set(current_by_id) - incoming_ids:
            db.session.delete(current_by_id[removed_id])
        for sprint in sprints:
            sprint_id_value = int(sprint.get("id"))
            row = current_by_id.get(sprint_id_value)
            if row is None:
                row = UserBoardSprint(
                    user_id=current_user.id,
                    board_id=board_id_int,
                    sprint_id=sprint_id_value,
                )
                db.session.add(row)
            row.sprint_name = (sprint.get("name") or "").strip()
            row.sprint_state = (sprint.get("state") or "").strip()
            row.sprint_url = (sprint.get("self") or "").strip()
            row.start_date = sprint.get("startDate")
            row.end_date = sprint.get("endDate")
            row.complete_date = sprint.get("completeDate")
            row.activated_date = sprint.get("activatedDate")
            row.origin_board_id = sprint.get("originBoardId")
            row.goal = sprint.get("goal")
            row.synced = bool(sprint.get("synced")) if sprint.get("synced") is not None else None
            row.auto_start_stop = (
                bool(sprint.get("autoStartStop"))
                if sprint.get("autoStartStop") is not None
                else None
            )
        if catalog is None:
            catalog = JiraSprintCatalog(
                user_id=current_user.id,
                source_id=source.id,
                board_id=board_id_int,
            )
            db.session.add(catalog)
        catalog.state = "complete"
        catalog.item_count = len(sprints)
        catalog.verified_at = datetime.now(UTC)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        log_handled_exception(
            "Failed to save Sprint Viewer sprints",
            exc,
            event="automation.sprint_viewer.sprints_save_failed",
            feature="sprint_viewer",
            operation="get_sprints",
            level=logging.ERROR,
            context={"board_id": board_id_int, "project_key": project_key},
        )
        return json_error("Failed to save sprints to DB.", status_code=500)

    saved = (
        UserBoardSprint.query.filter_by(user_id=current_user.id, board_id=board_id_int)
        .order_by(UserBoardSprint.sprint_id.desc())
        .all()
    )

    _trace_api(
        "SprintViewer/sprints saved user=%s board=%s count=%s",
        current_user.eid,
        board_id_int,
        len(saved),
    )

    return json_ok(
        source="jira",
        sprints=[
            {"id": s.sprint_id, "name": s.sprint_name, "state": s.sprint_state}
            for s in saved
        ],
    )


def sprint_viewer_fetch_issues():
    try:
        payload = require_json_object(request.get_json(silent=True))
        board_id_int = positive_jira_id(payload.get("board_id"), "Board ID")
        sprint_id_int = positive_jira_id(payload.get("sprint_id"), "Sprint ID")
    except InputValidationError as exc:
        return json_error(str(exc), status_code=400, code="INVALID_INPUT")

    if not _board_belongs_to_user(current_user.id, board_id_int):
        return json_error(
            "Selected board does not belong to your saved projects.",
            status_code=403,
        )
    sprint_row = UserBoardSprint.query.filter_by(
        user_id=current_user.id,
        board_id=board_id_int,
        sprint_id=sprint_id_int,
    ).first()
    if sprint_row is None:
        return json_error(
            "Selected sprint is not in the saved board catalog. Refresh sprints and try again.",
            status_code=404,
            code="SPRINT_NOT_IN_BOARD",
        )

    if _snapshot_mode():
        return _snapshot_fetch_issues(payload, board_id_int, sprint_id_int)

    try:
        pat = _get_user_pat()
        _validate_pat_belongs_to_user(pat)
    except JiraServiceError as exc:
        log_handled_exception(
            "Sprint Viewer PAT validation failed",
            exc,
            event="automation.sprint_viewer.pat_validation_failed",
            feature="sprint_viewer",
            operation="fetch_issues",
        )
        return json_error(safe_error_message("validate Jira access"), status_code=403)
    except Exception as exc:
        return json_error(str(exc), status_code=403)

    _trace_api(
        "SprintViewer/issues request user=%s board=%s sprint=%s",
        current_user.eid,
        board_id_int,
        sprint_id_int,
    )

    try:
        service = _sprint_service()
        raw = service.fetch_all_issues_for_sprint(sprint_id_int, pat)
        issues_raw = raw["issues"]
        sprint_meta = {
            "id": sprint_id_int,
            "name": sprint_row.sprint_name if sprint_row else "",
            "state": sprint_row.sprint_state if sprint_row else "",
            "start_date": sprint_row.start_date if sprint_row else None,
            "end_date": sprint_row.end_date if sprint_row else None,
            "activated_date": sprint_row.activated_date if sprint_row else None,
            "complete_date": sprint_row.complete_date if sprint_row else None,
            "goal": sprint_row.goal if sprint_row else None,
        }
        sprint_complete_date = sprint_meta["complete_date"]
        identity_resolver = service.build_identity_resolver(issues_raw)

        extracted = [
            service.extract_issue_fields(
                issue,
                sprint_complete_date=sprint_complete_date,
                resolver=identity_resolver,
            )
            for issue in issues_raw
        ]
        service.apply_relevant_comment_counts(
            extracted, sprint_complete_date=sprint_complete_date
        )
        grouped = service.group_issues_by_assignee(extracted)
        standard_issues = [issue for issue in extracted if not issue.get("is_subtask")]
        total_sp = service.sum_story_points(standard_issues)
        stats = service.compute_issue_quality_stats(standard_issues)
        work_type_mix = service.compute_work_type_mix(standard_issues)
        historical_fallback_count = sum(
            1 for issue in extracted if issue.get("historical_fallback")
        )

        _trace_api(
            "SprintViewer/issues done user=%s board=%s sprint=%s total=%s total_sp=%.2f unestimated=%s bugs=%s",
            current_user.eid,
            board_id_int,
            sprint_id_int,
            len(extracted),
            total_sp,
            stats.get("unestimated_count"),
            stats.get("bug_count"),
        )

        return json_ok(
            total=len(extracted),
            standard_total=len(standard_issues),
            total_sp=round(float(total_sp), 2),
            groups=grouped,
            stats=stats,
            sprint=sprint_meta,
            work_type_mix=work_type_mix,
            historical_fallback_count=historical_fallback_count,
        )
    except SprintViewerServiceError as exc:
        log_handled_exception(
            "Sprint Viewer failed to fetch issues",
            exc,
            event="automation.sprint_viewer.issues_failed",
            feature="sprint_viewer",
            operation="fetch_issues",
            context={"board_id": board_id_int, "sprint_id": sprint_id_int},
        )
        return json_error(safe_error_message("load sprint issues"), status_code=400)
    except Exception as exc:
        current_app.logger.exception("Unexpected error in sprint_viewer_fetch_issues: %s", exc)
        return json_error("Unexpected error occurred.", status_code=500)


def sprint_viewer_fetch_metrics():
    try:
        payload = require_json_object(request.get_json(silent=True))
        board_id_int = positive_jira_id(payload.get("board_id"), "Board ID")
        sprint_id_int = positive_jira_id(payload.get("sprint_id"), "Sprint ID")
        total_sp = payload.get("total_sp")
        total_count = payload.get("total_count")
        total_sp_val = float(total_sp) if total_sp is not None else 0.0
        total_count_val = int(total_count) if total_count is not None else 0
    except (InputValidationError, TypeError, ValueError) as exc:
        return json_error(
            str(exc) if isinstance(exc, InputValidationError) else "total_sp and total_count must be numeric.",
            status_code=400,
            code="INVALID_INPUT",
        )

    if not _board_belongs_to_user(current_user.id, board_id_int):
        return json_error(
            "Selected board does not belong to your saved projects.",
            status_code=403,
        )
    if UserBoardSprint.query.filter_by(
        user_id=current_user.id, board_id=board_id_int, sprint_id=sprint_id_int
    ).first() is None:
        return json_error(
            "Selected sprint is not in the saved board catalog. Refresh sprints and try again.",
            status_code=404,
            code="SPRINT_NOT_IN_BOARD",
        )

    if _snapshot_mode():
        return _snapshot_fetch_metrics(payload, board_id_int, sprint_id_int)

    try:
        pat = _get_user_pat()
        _validate_pat_belongs_to_user(pat)
    except JiraServiceError as exc:
        log_handled_exception(
            "Sprint Viewer PAT validation failed",
            exc,
            event="automation.sprint_viewer.pat_validation_failed",
            feature="sprint_viewer",
            operation="fetch_metrics",
        )
        return json_error(safe_error_message("validate Jira access"), status_code=403)
    except Exception as exc:
        return json_error(str(exc), status_code=403)

    _trace_api(
        "SprintViewer/metrics request user=%s board=%s sprint=%s total_sp=%.2f total_count=%s",
        current_user.eid,
        board_id_int,
        sprint_id_int,
        total_sp_val,
        total_count_val,
    )

    try:
        metrics = _sprint_service().compute_sprint_metrics_parallel(
            board_id=board_id_int,
            sprint_id=sprint_id_int,
            pat=pat,
            total_sp=total_sp_val,
            total_count=total_count_val,
        )

        _trace_api(
            "SprintViewer/metrics done user=%s board=%s sprint=%s keys=%s",
            current_user.eid,
            board_id_int,
            sprint_id_int,
            len(metrics.get("scope_added_keys") or []),
        )

        return json_ok(metrics=metrics)
    except SprintViewerServiceError as exc:
        log_handled_exception(
            "Sprint Viewer failed to fetch metrics",
            exc,
            event="automation.sprint_viewer.metrics_failed",
            feature="sprint_viewer",
            operation="fetch_metrics",
            context={"board_id": board_id_int, "sprint_id": sprint_id_int},
        )
        return json_error(safe_error_message("calculate sprint metrics"), status_code=400)
    except Exception as exc:
        current_app.logger.exception("Unexpected error in sprint_viewer_fetch_metrics: %s", exc)
        return json_error("Unexpected error occurred.", status_code=500)


def _snapshot_fetch_issues(payload: dict, board_id: int, sprint_id: int):
    try:
        if not current_user.jira_pat_enc:
            raise SnapshotAccessDenied("A Jira PAT is required")
        action_id = _client_action(payload)
        scope, snapshot, created = get_or_create_snapshot(
            current_user,
            board_id,
            sprint_id,
            request_id=getattr(request, "request_id", None),
        )
        if created:
            limited = consume_current_user_limit("sprint_import")
            if limited is not None:
                return limited
        view = create_report_view(
            current_user,
            scope,
            snapshot,
            action_id,
            request_id=getattr(request, "request_id", None),
        )
        db.session.commit()
        return json_accepted(**serialize_status(snapshot, view))
    except SnapshotNotFound as exc:
        db.session.rollback()
        return json_error(str(exc), status_code=404, code="SPRINT_NOT_IN_BOARD")
    except SnapshotAccessDenied as exc:
        db.session.rollback()
        return json_error(str(exc), status_code=403, code="REPORT_ACCESS_DENIED")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to initialize sprint snapshot: %s", exc)
        return json_error(safe_error_message("start the sprint report"), status_code=503, code="SNAPSHOT_ADMISSION_FAILED", retryable=True)


def _snapshot_fetch_metrics(payload: dict, board_id: int, sprint_id: int):
    try:
        scope, snapshot, _created = get_or_create_snapshot(current_user, board_id, sprint_id)
        view_id = payload.get("view_id")
        if view_id:
            view = owned_view(current_user, snapshot.id, _valid_uuid(view_id, "view_id"))
            if not _view_access_fresh(view):
                return json_error("Jira access must be checked again.", status_code=403, code="ACCESS_CHECK_EXPIRED")
        else:
            view = create_report_view(current_user, scope, snapshot, _client_action(payload))
        db.session.commit()
        state = serialize_status(snapshot, view)
        metrics_component = component_map(snapshot.id).get("metrics")
        if metrics_component and metrics_component.state == "ready" and (view.access_state or {}).get("metrics") == "granted":
            state["metrics"] = published_output(snapshot.id, "metrics")[1].output
            return json_ok(**state)
        return json_accepted(**state)
    except (SnapshotNotFound, InputValidationError) as exc:
        db.session.rollback()
        return json_error(str(exc), status_code=404, code="REPORT_NOT_FOUND")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to initialize sprint metrics: %s", exc)
        return json_error(safe_error_message("load sprint metrics"), status_code=503, code="SNAPSHOT_ADMISSION_FAILED", retryable=True)


def sprint_snapshot_status(snapshot_id: str):
    try:
        snapshot_id = _valid_uuid(snapshot_id, "snapshot_id")
        view_id = _valid_uuid(request.args.get("view_id"), "view_id")
        _scope, snapshot = owned_snapshot(current_user, snapshot_id)
        view = owned_view(current_user, snapshot_id, view_id)
        if any(value == "granted" for value in (view.access_state or {}).values()) and not _view_access_fresh(view):
            return json_error("Jira access must be checked again.", status_code=403, code="ACCESS_CHECK_EXPIRED")
        return json_ok(**serialize_status(snapshot, view))
    except (SnapshotNotFound, InputValidationError):
        return json_error("Report not found.", status_code=404, code="REPORT_NOT_FOUND")


def sprint_snapshot_issues(snapshot_id: str):
    try:
        snapshot_id = _valid_uuid(snapshot_id, "snapshot_id")
        view_id = _valid_uuid(request.args.get("view_id"), "view_id")
        _scope, snapshot = owned_snapshot(current_user, snapshot_id)
        view = owned_view(current_user, snapshot_id, view_id)
        if not _view_access_fresh(view):
            return json_error("Jira access must be checked again.", status_code=403, code="ACCESS_CHECK_EXPIRED")
        if (view.access_state or {}).get("core") != "granted":
            return json_accepted(state="processing", snapshot_id=snapshot.id, view_id=view.id, retry_after_ms=1500)
        _component, revision = published_output(snapshot.id, "core")
        requested_revision = request.args.get("revision")
        if requested_revision and str(revision.id) != str(requested_revision):
            return json_error("Requested revision is no longer available for this view.", status_code=409, code="REVISION_MISMATCH")
        try:
            limit = int(request.args.get("limit", "200"))
        except ValueError:
            raise InputValidationError("limit is invalid.")
        if limit < 1 or limit > 500:
            raise InputValidationError("limit must be between 1 and 500.")
        cursor = request.args.get("cursor") or None
        rows, next_cursor = core_issue_page(revision.id, cursor=cursor, limit=limit)
        service = _sprint_service()
        standard = [row for row in rows if not row.get("is_subtask")]
        payload = dict(revision.output or {})
        payload["groups"] = service.group_issues_by_assignee(rows)
        payload["issues_complete"] = next_cursor is None
        payload["next_cursor"] = next_cursor
        payload["page_limit"] = limit
        payload["snapshot_id"] = snapshot.id
        payload["view_id"] = view.id
        payload["generation"] = snapshot.generation
        payload["response_revision"] = snapshot.response_revision
        payload["source"] = "db"
        return json_ok(**payload)
    except (SnapshotNotFound, InputValidationError):
        return json_error("Report not found or request is invalid.", status_code=404, code="REPORT_NOT_FOUND")


def sprint_snapshot_component(snapshot_id: str, component_key: str):
    allowed = {"history", "comments", "metrics", *METRIC_CATEGORIES}
    if component_key not in allowed:
        return json_error("Unknown component.", status_code=404, code="COMPONENT_NOT_FOUND")
    try:
        snapshot_id = _valid_uuid(snapshot_id, "snapshot_id")
        view_id = _valid_uuid(request.args.get("view_id"), "view_id")
        _scope, snapshot = owned_snapshot(current_user, snapshot_id)
        view = owned_view(current_user, snapshot_id, view_id)
        if not _view_access_fresh(view):
            return json_error("Jira access must be checked again.", status_code=403, code="ACCESS_CHECK_EXPIRED")
        access_key = "metrics" if component_key in {*METRIC_CATEGORIES, "metrics"} else component_key
        if (view.access_state or {}).get(access_key) != "granted":
            components = component_map(snapshot.id)
            state = components[component_key].state
            if state in {"failed", "unavailable"}:
                return json_error("Component is unavailable.", status_code=409, code=components[component_key].error_code or "COMPONENT_UNAVAILABLE")
            return json_accepted(state="processing", component=component_key, retry_after_ms=1500)
        component, revision = published_output(snapshot.id, component_key)
        requested_revision = request.args.get("revision")
        if requested_revision and str(revision.id) != str(requested_revision):
            return json_error("Component revision mismatch.", status_code=409, code="REVISION_MISMATCH")
        return json_ok(
            source="db",
            snapshot_id=snapshot.id,
            generation=snapshot.generation,
            component=component_key,
            revision=revision.id,
            data=revision.output,
        )
    except (SnapshotNotFound, InputValidationError):
        return json_error("Report not found.", status_code=404, code="REPORT_NOT_FOUND")


def sprint_snapshot_retry(snapshot_id: str):
    try:
        payload = require_json_object(request.get_json(silent=True))
        snapshot_id = _valid_uuid(snapshot_id, "snapshot_id")
        view_id = _valid_uuid(payload.get("view_id"), "view_id")
        component_key = str(payload.get("component") or "")
        allowed = {"history", "comments", *METRIC_CATEGORIES, "metrics"}
        if component_key not in allowed:
            raise InputValidationError("component is invalid.")
        scope, snapshot = owned_snapshot(current_user, snapshot_id)
        view = owned_view(current_user, snapshot_id, view_id)
        if not _view_access_fresh(view) or (view.access_state or {}).get("core") != "granted":
            return json_error("Jira access must be checked again.", status_code=403, code="ACCESS_CHECK_EXPIRED")
        component = component_map(snapshot.id)[component_key]
        if component.state not in {"failed", "unavailable"}:
            return json_error("Component is not retryable in its current state.", status_code=409, code="INVALID_COMPONENT_STATE")
        component.state = "queued"
        job_type = "sprint_metrics_final" if component_key == "metrics" else ("sprint_metric" if component_key in METRIC_CATEGORIES else f"sprint_{component_key}")
        job = enqueue_job(scope.id, job_type=job_type, snapshot_id=snapshot.id,
                          component_key=component_key, lane="enrichment", priority=30,
                          dedupe_suffix=f"retry:{component_key}:{component.next_revision}")
        if component_key in METRIC_CATEGORIES:
            job.cursor = {"category": component_key}
        db.session.commit()
        return json_accepted(**serialize_status(snapshot, owned_view(current_user, snapshot_id, view_id)))
    except (SnapshotNotFound, InputValidationError):
        db.session.rollback()
        return json_error("Report not found or request is invalid.", status_code=404, code="REPORT_NOT_FOUND")


def sprint_snapshot_authorize(snapshot_id: str):
    try:
        payload = require_json_object(request.get_json(silent=True))
        snapshot_id = _valid_uuid(snapshot_id, "snapshot_id")
        scope, snapshot = owned_snapshot(current_user, snapshot_id)
        purpose = str(payload.get("purpose") or "view")
        if purpose not in {"view", "export"}:
            raise InputValidationError("purpose is invalid.")
        view = create_report_view(current_user, scope, snapshot, _client_action(payload), purpose=purpose)
        db.session.commit()
        return json_accepted(**serialize_status(snapshot, view))
    except (SnapshotNotFound, InputValidationError):
        db.session.rollback()
        return json_error("Report not found or request is invalid.", status_code=404, code="REPORT_NOT_FOUND")


def sprint_snapshot_export_manifest(snapshot_id: str):
    try:
        snapshot_id = _valid_uuid(snapshot_id, "snapshot_id")
        view_id = _valid_uuid(request.args.get("view_id"), "view_id")
        _scope, snapshot = owned_snapshot(current_user, snapshot_id)
        view = owned_view(current_user, snapshot_id, view_id)
        if not _view_access_fresh(view):
            return json_error("Jira access must be checked again.", status_code=403, code="ACCESS_CHECK_EXPIRED")
        components = component_map(snapshot.id)
        if view.purpose != "export" or not export_ready(snapshot, view, components):
            return json_error("Report is not ready or export access has not been granted.", status_code=409, code="EXPORT_NOT_READY")
        revision_map = {key: value.published_revision_id for key, value in components.items() if value.published_revision_id}
        return json_ok(
            snapshot_id=snapshot.id,
            generation=snapshot.generation,
            revisions=revision_map,
            availability={key: value.state for key, value in components.items()},
            issues_url=url_for("aliases.api_sprint_snapshot_issues", snapshot_id=snapshot.id, view_id=view.id, revision=revision_map["core"], limit=500),
            components_url_template=url_for("aliases.api_sprint_snapshot_component", snapshot_id=snapshot.id, component_key="__component__", view_id=view.id),
            access_checked_at=view.created_at.isoformat(),
            time_basis={"tickets": "at sprint completion when verified", "metrics": "Jira points at collection time"},
        )
    except (SnapshotNotFound, InputValidationError):
        return json_error("Report not found.", status_code=404, code="REPORT_NOT_FOUND")
