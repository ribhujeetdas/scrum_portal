from __future__ import annotations

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ....core.api import safe_error_message
from ....core.database import execute_write
from ....core.dependencies import crypto_service
from ....core.error_logging import log_handled_exception
from ....extensions import db
from ....logging_conf import audit_event
from ....models import UserBoard, UserProject
from ....services.jira_projects_service import JiraProjectsService, JiraProjectsServiceError
from ....services.profile_service import (
    DeleteBoardRequest,
    DeleteProjectRequest,
    ProfileService,
    ProfileServiceError,
)
from .forms import AddProjectForm, DeleteBoardForm, DeleteProjectForm


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
            return redirect(url_for("aliases.settings_projects_boards"))

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
        return redirect(url_for("aliases.settings_projects_boards"))
    try:
        pat = crypto_service().decrypt(current_user.jira_pat_enc)
    except Exception:
        flash(
            "Unable to read your saved PAT. Please re-save it under Settings -> Integrations.",
            "danger",
        )
        return redirect(url_for("aliases.settings_projects_boards"))

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
        flash(safe_error_message("validate Jira project permissions"), "danger")
        return redirect(url_for("aliases.settings_projects_boards"))
    if not has_admin:
        flash(
            f"You do NOT have ADMINISTER_PROJECTS permission for project {project_key}.",
            "danger",
        )
        return redirect(url_for("aliases.settings_projects_boards"))

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
        flash(safe_error_message("load Jira boards for the project"), "danger")
        return redirect(url_for("aliases.settings_projects_boards"))

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
    except Exception:
        current_app.logger.exception(
            "Unexpected Product Area key detection error",
            extra={
                "event": "settings.projects.product_area_detection_unexpected",
                "resource_type": "jira_project",
                "resource_id": project_key,
            },
        )
    return product_area_key


def _save_project_boards(project_key: str, boards: list[dict], product_area_key: str | None):
    try:

        def _save() -> None:
            project = UserProject.query.filter_by(
                user_id=current_user.id, project_key=project_key
            ).first()
            if not project:
                project = UserProject(
                    user_id=current_user.id,
                    project_key=project_key,
                    admin_projects=True,
                )
                db.session.add(project)
                db.session.flush()
            else:
                project.admin_projects = True
                UserBoard.query.filter_by(project_id=project.id).delete(synchronize_session=False)

            project.epic_key = product_area_key or None
            for board in boards:
                db.session.add(
                    UserBoard(
                        project_id=project.id,
                        board_id=board["board_id"],
                        board_name=board["board_name"],
                        board_type=board["board_type"],
                        board_url=board["board_url"],
                    )
                )

        execute_write(_save, retries=0)
        audit_event(
            "settings.projects.saved",
            "Project and board settings saved",
            resource_type="jira_project",
            resource_id=project_key,
            result="success",
        )
        current_app.logger.info(
            "Project and boards saved",
            extra={
                "event": "settings.projects.saved",
                "resource_type": "jira_project",
                "resource_id": project_key,
                "result": "success",
            },
        )
        if product_area_key:
            flash(
                f"Project {project_key} added successfully. Boards saved: {len(boards)}. "
                f"Epic key captured: {product_area_key}",
                "success",
            )
        else:
            flash(
                f"Project {project_key} added successfully. Boards saved: {len(boards)}. "
                f"Epic key not found for boards (will remain empty).",
                "success",
            )
    except Exception:
        current_app.logger.exception(
            "Project and board persistence failed",
            extra={
                "event": "settings.projects.save_failed",
                "resource_type": "jira_project",
                "resource_id": project_key,
                "result": "failed",
            },
        )
        flash("Failed to save project/boards. Please check logs.", "danger")
    return redirect(url_for("aliases.settings_projects_boards"))


def _handle_delete_project(delete_project_form, svc: ProfileService):
    if not delete_project_form.validate_on_submit():
        current_app.logger.warning(
            "Delete project validation failed",
            extra={
                "event": "settings.projects.delete_validation_failed",
                "result": "rejected",
            },
        )
        flash(
            "Delete failed due to an invalid request (please refresh and try again).",
            "danger",
        )
        return redirect(url_for("aliases.settings_projects_boards"))
    project_key = (delete_project_form.delete_project_key.data or "").strip().upper()
    try:
        removed = svc.delete_project(
            DeleteProjectRequest(user_id=current_user.id, project_key=project_key)
        )
        audit_event(
            "settings.projects.deleted",
            "Project settings deleted",
            resource_type="jira_project",
            resource_id=project_key,
            result="success",
        )
        flash(
            f"Project {project_key} deleted successfully (boards removed: {removed}).",
            "success",
        )
    except ProfileServiceError as exc:
        log_handled_exception(
            "Delete project rejected",
            exc,
            event="settings.projects.delete_project_rejected",
            feature="projects_boards",
            operation="delete_project",
            context={"project_key": project_key},
        )
        flash(safe_error_message("delete the project"), "danger")
    except Exception:
        current_app.logger.exception(
            "Unexpected project deletion error",
            extra={
                "event": "settings.projects.delete_failed",
                "resource_type": "jira_project",
                "resource_id": project_key,
                "result": "failed",
            },
        )
        flash("Unexpected error occurred while deleting the project.", "danger")
    return redirect(url_for("aliases.settings_projects_boards"))


def _handle_delete_board(delete_board_form, svc: ProfileService):
    if not delete_board_form.validate_on_submit():
        current_app.logger.warning(
            "Delete board validation failed",
            extra={
                "event": "settings.boards.delete_validation_failed",
                "result": "rejected",
            },
        )
        flash(
            "Delete failed due to an invalid request (please refresh and try again).",
            "danger",
        )
        return redirect(url_for("aliases.settings_projects_boards"))
    project_key = (delete_board_form.delete_project_key.data or "").strip().upper()
    board_id_raw = (delete_board_form.delete_board_id.data or "").strip()
    try:
        board_id = int(board_id_raw)
    except ValueError:
        flash("Invalid Board ID.", "danger")
        return redirect(url_for("aliases.settings_projects_boards"))
    try:
        project_deleted = svc.delete_board(
            DeleteBoardRequest(user_id=current_user.id, project_key=project_key, board_id=board_id)
        )
        audit_event(
            "settings.boards.deleted",
            "Board settings deleted",
            resource_type="jira_board",
            resource_id=str(board_id),
            result="success",
        )
        if project_deleted:
            flash(
                f"Board {board_id} deleted successfully. Project {project_key} was also removed because it had no remaining boards.",
                "success",
            )
        else:
            flash(f"Board {board_id} deleted successfully.", "success")
    except ProfileServiceError as exc:
        log_handled_exception(
            "Delete board rejected",
            exc,
            event="settings.projects.delete_board_rejected",
            feature="projects_boards",
            operation="delete_board",
            context={"project_key": project_key, "board_id": board_id},
        )
        flash(safe_error_message("delete the board"), "danger")
    except Exception:
        current_app.logger.exception(
            "Unexpected board deletion error",
            extra={
                "event": "settings.boards.delete_failed",
                "resource_type": "jira_board",
                "resource_id": str(board_id),
                "result": "failed",
            },
        )
        flash("Unexpected error occurred while deleting the board.", "danger")
    return redirect(url_for("aliases.settings_projects_boards"))
