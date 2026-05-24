from __future__ import annotations

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from .forms import AddProjectForm, DeleteBoardForm, DeleteProjectForm
from ....core.dependencies import crypto_service
from ....core.error_logging import log_handled_exception
from ....extensions import db
from ....models import UserBoard, UserProject
from ....services.jira_projects_service import JiraProjectsService, JiraProjectsServiceError
from ....services.profile_service import (
    DeleteBoardRequest,
    DeleteProjectRequest,
    ProfileService,
    ProfileServiceError,
)


def _load_user_projects():
    return (
        UserProject.query.filter_by(user_id=current_user.id)
        .order_by(UserProject.project_key.asc())
        .all()
    )


def projects_page():
    """
    Settings -> Projects & Boards.

    Existing config routes delegate here so the public endpoint remains stable.
    """
    project_form = AddProjectForm()
    delete_project_form = DeleteProjectForm()
    delete_board_form = DeleteBoardForm()
    svc = ProfileService()
    user_projects = _load_user_projects()

    if request.method == "POST":
        if "validate_and_add" in request.form and not project_form.validate_on_submit():
            messages = []
            for errors in project_form.errors.values():
                messages.extend(errors)
            flash(" ".join(messages) or "Please provide a valid Jira project key.", "danger")
            return redirect(url_for("config.projects"))

        if "validate_and_add" in request.form and project_form.validate_on_submit():
            return _handle_add_project(project_form)

        if "delete_project" in request.form:
            return _handle_delete_project(delete_project_form, svc)

        if "delete_board" in request.form:
            return _handle_delete_board(delete_board_form, svc)

        user_projects = _load_user_projects()

    return render_template(
        "config/projects_boards.html",
        project_form=project_form,
        delete_project_form=delete_project_form,
        delete_board_form=delete_board_form,
        user_projects=user_projects,
    )


def _handle_add_project(project_form):
    if not current_user.jira_pat_enc:
        flash(
            "Please set your Enterprise Agile Jira PAT first under Settings -> Integrations.",
            "warning",
        )
        return redirect(url_for("config.projects"))
    try:
        pat = crypto_service().decrypt(current_user.jira_pat_enc)
    except Exception:
        flash(
            "Unable to read your saved PAT. Please re-save it under Settings -> Integrations.",
            "danger",
        )
        return redirect(url_for("config.projects"))

    project_key = (project_form.project_key.data or "").strip().upper()
    jps = JiraProjectsService(current_app.config["JIRA_BASE_URL"])

    try:
        has_admin = jps.has_administer_projects(project_key, pat)
    except JiraProjectsServiceError as exc:
        log_handled_exception(
            "Project permission check failed",
            exc,
            event="settings.projects.permission_check_failed",
            feature="projects_boards",
            operation="check_project_permissions",
            context={"project_key": project_key},
        )
        flash(str(exc), "danger")
        return redirect(url_for("config.projects"))
    if not has_admin:
        flash(
            f"You do NOT have ADMINISTER_PROJECTS permission for project {project_key}.",
            "danger",
        )
        return redirect(url_for("config.projects"))

    try:
        boards = jps.list_boards_for_project(project_key, pat)
    except JiraProjectsServiceError as exc:
        log_handled_exception(
            "Board list failed",
            exc,
            event="settings.projects.board_list_failed",
            feature="projects_boards",
            operation="list_project_boards",
            context={"project_key": project_key},
        )
        flash(str(exc), "danger")
        return redirect(url_for("config.projects"))

    product_area_key = _detect_product_area_key(jps, boards, project_key, pat)
    return _save_project_boards(project_key, boards, product_area_key)


def _detect_product_area_key(jps, boards, project_key: str, pat: str):
    product_area_key = None
    try:
        for board in boards:
            board_id = int(board.get("board_id"))
            maybe_key = jps.get_product_area_project_key_for_board(board_id, pat)
            if maybe_key:
                product_area_key = maybe_key
                break
    except JiraProjectsServiceError as exc:
        log_handled_exception(
            "Product Area key detection failed",
            exc,
            event="settings.projects.product_area_detection_failed",
            feature="projects_boards",
            operation="detect_product_area_key",
            context={"project_key": project_key},
        )
    except Exception as exc:
        current_app.logger.exception(
            "Unexpected Product Area key detection error eid=%s project=%s err=%s",
            current_user.eid, project_key, exc
        )
    return product_area_key


def _save_project_boards(project_key: str, boards: list[dict], product_area_key: str | None):
    try:
        proj = UserProject.query.filter_by(
            user_id=current_user.id, project_key=project_key).first()
        if not proj:
            proj = UserProject(
                user_id=current_user.id,
                project_key=project_key,
                admin_projects=True,
            )
            db.session.add(proj)
            db.session.flush()
        else:
            proj.admin_projects = True
            UserBoard.query.filter_by(project_id=proj.id).delete()

        proj.epic_key = (product_area_key or None)
        for board in boards:
            db.session.add(
                UserBoard(
                    project_id=proj.id,
                    board_id=board["board_id"],
                    board_name=board["board_name"],
                    board_type=board["board_type"],
                    board_url=board["board_url"],
                )
            )
        db.session.commit()
        current_app.logger.info(
            "Project added eid=%s project=%s boards=%s product_area_key=%s",
            current_user.eid, project_key, len(boards), product_area_key
        )
        if product_area_key:
            flash(
                f"Project {project_key} added successfully. Boards saved: {len(boards)}. "
                f"Epic key captured: {product_area_key}",
                "success"
            )
        else:
            flash(
                f"Project {project_key} added successfully. Boards saved: {len(boards)}. "
                f"Epic key not found for boards (will remain empty).",
                "success"
            )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(
            "DB save failed eid=%s project=%s err=%s",
            current_user.eid, project_key, exc
        )
        flash("Failed to save project/boards. Please check logs.", "danger")
    return redirect(url_for("config.projects"))


def _handle_delete_project(delete_project_form, svc: ProfileService):
    if not delete_project_form.validate_on_submit():
        current_app.logger.warning(
            "Delete project validation failed eid=%s errors=%s form=%s",
            current_user.eid, delete_project_form.errors, dict(request.form)
        )
        flash(
            "Delete failed due to an invalid request (please refresh and try again).",
            "danger",
        )
        return redirect(url_for("config.projects"))
    project_key = (
        delete_project_form.delete_project_key.data or "").strip().upper()
    try:
        removed = svc.delete_project(DeleteProjectRequest(
            user_id=current_user.id, project_key=project_key))
        flash(
            f"Project {project_key} deleted successfully (boards removed: {removed}).",
            "success",
        )
    except ProfileServiceError as exc:
        current_app.logger.warning(
            "Delete project rejected eid=%s project=%s reason=%s",
            current_user.eid, project_key, str(exc)
        )
        flash(str(exc), "danger")
    except Exception as exc:
        current_app.logger.exception(
            "Unexpected delete project error eid=%s project=%s err=%s",
            current_user.eid, project_key, exc
        )
        flash("Unexpected error occurred while deleting the project.", "danger")
    return redirect(url_for("config.projects"))


def _handle_delete_board(delete_board_form, svc: ProfileService):
    if not delete_board_form.validate_on_submit():
        current_app.logger.warning(
            "Delete board validation failed eid=%s errors=%s form=%s",
            current_user.eid, delete_board_form.errors, dict(request.form)
        )
        flash(
            "Delete failed due to an invalid request (please refresh and try again).",
            "danger",
        )
        return redirect(url_for("config.projects"))
    project_key = (
        delete_board_form.delete_project_key.data or "").strip().upper()
    board_id_raw = (
        delete_board_form.delete_board_id.data or "").strip()
    try:
        board_id = int(board_id_raw)
    except ValueError:
        flash("Invalid Board ID.", "danger")
        return redirect(url_for("config.projects"))
    try:
        project_deleted = svc.delete_board(DeleteBoardRequest(
            user_id=current_user.id,
            project_key=project_key,
            board_id=board_id
        ))
        if project_deleted:
            flash(
                f"Board {board_id} deleted successfully. Project {project_key} was also removed because it had no remaining boards.",
                "success",
            )
        else:
            flash(f"Board {board_id} deleted successfully.", "success")
    except ProfileServiceError as exc:
        current_app.logger.warning(
            "Delete board rejected eid=%s project=%s board_id=%s reason=%s",
            current_user.eid, project_key, board_id, str(exc)
        )
        flash(str(exc), "danger")
    except Exception as exc:
        current_app.logger.exception(
            "Unexpected delete board error eid=%s project=%s board_id=%s err=%s",
            current_user.eid, project_key, board_id, exc
        )
        flash("Unexpected error occurred while deleting the board.", "danger")
    return redirect(url_for("config.projects"))
