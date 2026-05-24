from __future__ import annotations

import logging

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ....core.api import json_error, json_ok
from ....core.dependencies import crypto_service, jira_service, sprint_viewer_service
from ....core.error_logging import log_handled_exception
from ....extensions import db
from ....models import UserBoard, UserBoardSprint, UserProject
from ....services.jira_service import JiraServiceError
from ....services.sprint_viewer_service import SprintViewerService, SprintViewerServiceError


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
    myself = jira_service().fetch_myself(pat)
    api_email = (myself.get("emailAddress") or "").strip()
    active = bool(myself.get("active"))
    deleted = bool(myself.get("deleted"))
    if api_email.lower() != current_user.email.lower():
        raise ValueError("Saved PAT belongs to a different user (email mismatch).")
    if not active or deleted:
        raise ValueError("Jira profile is not active or is deleted.")


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


def sprint_viewer_page():
    projects = (
        UserProject.query.filter_by(user_id=current_user.id, admin_projects=True)
        .order_by(UserProject.project_key.asc())
        .all()
    )
    if not projects:
        flash(
            "No project key found. Redirecting you to Settings to add Projects & Boards.",
            "warning",
        )
        return redirect(url_for("config.projects"))

    boards_by_project: dict[str, list[dict]] = {}
    for project in projects:
        boards = (
            UserBoard.query.join(UserProject, UserBoard.project_id == UserProject.id)
            .filter(UserProject.user_id == current_user.id, UserProject.id == project.id)
            .order_by(UserBoard.board_name.asc())
            .all()
        )
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
    )


def sprint_viewer_get_sprints():
    payload = request.get_json(silent=True) or {}
    project_key = str(payload.get("project_key") or "").strip().upper()
    board_id = payload.get("board_id")
    refresh = bool(payload.get("refresh", False))

    try:
        board_id_int = int(board_id)
    except Exception:
        return json_error("Board ID must be numeric.", status_code=400)

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
        return json_error(f"PAT validation failed: {exc}", status_code=403)
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

    if refresh:
        try:
            UserBoardSprint.query.filter_by(
                user_id=current_user.id, board_id=board_id_int
            ).delete()
            db.session.commit()
            existing = []
        except Exception as exc:
            db.session.rollback()
            log_handled_exception(
                "Failed to clear Sprint Viewer cache",
                exc,
                event="automation.sprint_viewer.sprints_clear_failed",
                feature="sprint_viewer",
                operation="get_sprints",
                level=logging.ERROR,
                context={"board_id": board_id_int, "project_key": project_key},
            )
            return json_error("Failed to clear existing sprints from DB.", status_code=500)

    if existing:
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
        return json_error(str(exc), status_code=400)

    try:
        for sprint in sprints:
            db.session.add(
                UserBoardSprint(
                    user_id=current_user.id,
                    board_id=board_id_int,
                    sprint_id=int(sprint.get("id")),
                    sprint_name=(sprint.get("name") or "").strip(),
                    sprint_state=(sprint.get("state") or "").strip(),
                    sprint_url=(sprint.get("self") or "").strip(),
                    start_date=sprint.get("startDate"),
                    end_date=sprint.get("endDate"),
                    complete_date=sprint.get("completeDate"),
                    activated_date=sprint.get("activatedDate"),
                    origin_board_id=sprint.get("originBoardId"),
                    goal=sprint.get("goal"),
                    synced=bool(sprint.get("synced"))
                    if sprint.get("synced") is not None
                    else None,
                    auto_start_stop=bool(sprint.get("autoStartStop"))
                    if sprint.get("autoStartStop") is not None
                    else None,
                )
            )
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
    payload = request.get_json(silent=True) or {}
    board_id = payload.get("board_id")
    sprint_id = payload.get("sprint_id")

    try:
        board_id_int = int(board_id)
        sprint_id_int = int(sprint_id)
    except Exception:
        return json_error("Board ID and Sprint ID must be numeric.", status_code=400)

    if not _board_belongs_to_user(current_user.id, board_id_int):
        return json_error(
            "Selected board does not belong to your saved projects.",
            status_code=403,
        )

    try:
        pat = _get_user_pat()
        _validate_pat_belongs_to_user(pat)
    except JiraServiceError as exc:
        return json_error(f"PAT validation failed: {exc}", status_code=403)
    except Exception as exc:
        return json_error(str(exc), status_code=403)

    _trace_api(
        "SprintViewer/issues request user=%s board=%s sprint=%s",
        current_user.eid,
        board_id_int,
        sprint_id_int,
    )

    try:
        raw = _sprint_service().fetch_all_issues_for_sprint(sprint_id_int, pat)
        total = raw["total"]
        issues_raw = raw["issues"]

        extracted = [_sprint_service().extract_issue_fields(issue) for issue in issues_raw]
        grouped = _sprint_service().group_issues_by_assignee(extracted)
        total_sp = _sprint_service().sum_story_points(extracted)
        stats = _sprint_service().compute_issue_quality_stats(extracted)

        _trace_api(
            "SprintViewer/issues done user=%s board=%s sprint=%s total=%s total_sp=%.2f unestimated=%s bugs=%s",
            current_user.eid,
            board_id_int,
            sprint_id_int,
            total,
            total_sp,
            stats.get("unestimated_count"),
            stats.get("bug_count"),
        )

        return json_ok(
            total=int(total),
            total_sp=round(float(total_sp), 2),
            groups=grouped,
            stats=stats,
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
        return json_error(str(exc), status_code=400)
    except Exception as exc:
        current_app.logger.exception("Unexpected error in sprint_viewer_fetch_issues: %s", exc)
        return json_error("Unexpected error occurred.", status_code=500)


def sprint_viewer_fetch_metrics():
    payload = request.get_json(silent=True) or {}
    board_id = payload.get("board_id")
    sprint_id = payload.get("sprint_id")
    total_sp = payload.get("total_sp")
    total_count = payload.get("total_count")

    try:
        board_id_int = int(board_id)
        sprint_id_int = int(sprint_id)
        total_sp_val = float(total_sp) if total_sp is not None else 0.0
        total_count_val = int(total_count) if total_count is not None else 0
    except Exception:
        return json_error(
            "Board ID and Sprint ID must be numeric; total_sp and total_count must be numeric.",
            status_code=400,
        )

    if not _board_belongs_to_user(current_user.id, board_id_int):
        return json_error(
            "Selected board does not belong to your saved projects.",
            status_code=403,
        )

    try:
        pat = _get_user_pat()
        _validate_pat_belongs_to_user(pat)
    except JiraServiceError as exc:
        return json_error(f"PAT validation failed: {exc}", status_code=403)
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
        return json_error(str(exc), status_code=400)
    except Exception as exc:
        current_app.logger.exception("Unexpected error in sprint_viewer_fetch_metrics: %s", exc)
        return json_error("Unexpected error occurred.", status_code=500)
