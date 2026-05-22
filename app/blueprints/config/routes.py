# app/blueprints/config/routes.py
from __future__ import annotations
from flask import current_app, render_template, flash, redirect, url_for, request
from flask_login import login_required, current_user
from . import config_bp
from .forms import (
    JiraConfigForm,
    TableauConfigForm,
    AddProjectForm,
    TableauCustomViewForm,
    TableauCustomViewDeleteForm,
    DeleteProjectForm,
    DeleteBoardForm,
)
from ...extensions import db
from ...models import UserProject, UserBoard, UserTableauCustomView
from ...services.crypto_service import CryptoService
from ...services.jira_service import JiraService, JiraServiceError
from ...services.jira_projects_service import JiraProjectsService, JiraProjectsServiceError
from ...services.tableau_service import TableauService, TableauServiceError
from ...services.profile_service import (
    ProfileService,
    ProfileServiceError,
    DeleteProjectRequest,
    DeleteBoardRequest,
)


def _crypto() -> CryptoService:
    return CryptoService(current_app.config["FERNET_KEY"])


def _jira_service() -> JiraService:
    return JiraService(current_app.config["JIRA_BASE_URL"])


def _tableau_service() -> TableauService:
    return TableauService(
        base_url=current_app.config.get("TABLEAU_BASE_URL", ""),
        api_version=current_app.config.get("TABLEAU_API_VERSION", "3.25"),
        site_content_url=current_app.config.get(
            "TABLEAU_SITE_CONTENT_URL", ""),
    )


def _masked_jira_token() -> str:
    if not current_user.jira_pat_enc:
        return "Not set"
    try:
        pat = _crypto().decrypt(current_user.jira_pat_enc)
        return ("*" * max(0, len(pat) - 4)) + pat[-4:]
    except Exception:
        return "******"


def _masked_tableau_secret() -> str:
    if not getattr(current_user, "tableau_pat_secret_enc", None):
        return "Not set"
    try:
        sec = _crypto().decrypt(current_user.tableau_pat_secret_enc)
        return ("*" * max(0, len(sec) - 4)) + sec[-4:]
    except Exception:
        return "******"


@config_bp.route("/", methods=["GET"])
@login_required
def index():
    # Default Settings page -> Integrations
    return redirect(url_for("config.integrations"))


@config_bp.route("/integrations", methods=["GET", "POST"])
@login_required
def integrations():
    pat_form = JiraConfigForm()
    tableau_form = TableauConfigForm()
    masked_token = _masked_jira_token()
    masked_tableau_token = _masked_tableau_secret()
    tableau_pat_name_saved = getattr(
        current_user, "tableau_pat_name", None) or ""
    if request.method == "POST":
        # A) Validate & Save Jira PAT
        if "validate_and_save" in request.form and pat_form.validate_on_submit():
            pat_input = (pat_form.jira_pat.data or "").strip()
            try:
                profile_json = _jira_service().fetch_myself(pat_input)
            except JiraServiceError as exc:
                current_app.logger.warning(
                    "Jira PAT validate failed eid=%s email=%s reason=%s",
                    current_user.eid, current_user.email, str(exc)
                )
                flash(str(exc), "danger")
                return redirect(url_for("config.integrations"))
            api_email = (profile_json.get("emailAddress") or "").strip()
            active = bool(profile_json.get("active"))
            deleted = bool(profile_json.get("deleted"))
            if api_email.lower() != current_user.email.lower():
                flash("Token belongs to a different user (email mismatch).", "danger")
                return redirect(url_for("config.integrations"))
            if not active or deleted:
                flash("Jira profile is not active or is deleted.", "danger")
                return redirect(url_for("config.integrations"))
            current_user.jira_pat_enc = _crypto().encrypt(pat_input)
            db.session.commit()
            current_app.logger.info(
                "User updated Jira PAT eid=%s email=%s", current_user.eid, current_user.email)
            flash("Token validated and saved successfully.", "success")
            return redirect(url_for("config.integrations"))
        # B) Validate & Save Tableau PAT
        if "tableau_validate_and_save" in request.form and tableau_form.validate_on_submit():
            pat_name = (tableau_form.tableau_pat_name.data or "").strip()
            pat_secret = (tableau_form.tableau_pat_secret.data or "").strip()
            try:
                identity = _tableau_service().validate_pat_and_get_identity(pat_name, pat_secret)
            except (TableauServiceError, ValueError) as exc:
                current_app.logger.warning(
                    "Tableau PAT validate failed eid=%s email=%s reason=%s",
                    current_user.eid, current_user.email, str(exc)
                )
                flash(str(exc), "danger")
                return redirect(url_for("config.integrations"))
            except Exception as exc:
                current_app.logger.exception(
                    "Unexpected Tableau validation error: %s", exc)
                flash(
                    "Unexpected error occurred while validating Tableau PAT.", "danger")
                return redirect(url_for("config.integrations"))
            tableau_email = (identity.get("email") or "").strip()
            tableau_eid = (identity.get("eid") or "").strip()
            if tableau_email.lower() != current_user.email.lower():
                flash(
                    f"Tableau user email '{tableau_email}' does not match your registered email '{current_user.email}'.",
                    "danger",
                )
                return redirect(url_for("config.integrations"))
            if tableau_eid.lower() != current_user.eid.lower():
                flash(
                    f"Tableau user name/EID '{tableau_eid}' does not match your registered EID '{current_user.eid}'.",
                    "danger",
                )
                return redirect(url_for("config.integrations"))
            current_user.tableau_pat_name = pat_name
            current_user.tableau_pat_secret_enc = _crypto().encrypt(pat_secret)
            current_user.tableau_site_id = identity.get("site_id")
            current_user.tableau_user_id = identity.get("user_id")
            current_user.tableau_content_url = identity.get("content_url")
            current_user.tableau_email = tableau_email
            current_user.tableau_eid = tableau_eid
            db.session.commit()
            current_app.logger.info(
                "User updated Tableau PAT eid=%s email=%s", current_user.eid, current_user.email)
            flash("Tableau PAT validated and saved successfully.", "success")
            return redirect(url_for("config.integrations"))
    return render_template(
        "config/integrations.html",
        pat_form=pat_form,
        tableau_form=tableau_form,
        masked_token=masked_token,
        masked_tableau_token=masked_tableau_token,
        tableau_pat_name_saved=tableau_pat_name_saved,
    )


@config_bp.route("/projects", methods=["GET", "POST"])
@login_required
def projects():
    """
    Settings -> Projects & Boards
    - Add Project (Validate & Add)
    - Delete Project
    - Delete Board
    """
    project_form = AddProjectForm()
    delete_project_form = DeleteProjectForm()
    delete_board_form = DeleteBoardForm()
    svc = ProfileService()
    user_projects = (
        UserProject.query.filter_by(user_id=current_user.id)
        .order_by(UserProject.project_key.asc())
        .all()
    )
    if request.method == "POST":
        # ------------------------------------------------------------------
        # Add Project
        # ------------------------------------------------------------------
        if "validate_and_add" in request.form and project_form.validate_on_submit():
            if not current_user.jira_pat_enc:
                flash(
                    "Please set your Enterprise Agile Jira PAT first under Settings → Integrations.", "warning")
                return redirect(url_for("config.projects"))
            try:
                pat = _crypto().decrypt(current_user.jira_pat_enc)
            except Exception:
                flash(
                    "Unable to read your saved PAT. Please re-save it under Settings → Integrations.", "danger")
                return redirect(url_for("config.projects"))
            project_key = (project_form.project_key.data or "").strip().upper()
            jps = JiraProjectsService(current_app.config["JIRA_BASE_URL"])
            # 1) Check ADMINISTER_PROJECTS
            try:
                has_admin = jps.has_administer_projects(project_key, pat)
            except JiraProjectsServiceError as exc:
                current_app.logger.warning(
                    "Project permission check failed eid=%s project=%s reason=%s",
                    current_user.eid, project_key, str(exc)
                )
                flash(str(exc), "danger")
                return redirect(url_for("config.projects"))
            if not has_admin:
                flash(
                    f"You do NOT have ADMINISTER_PROJECTS permission for project {project_key}.", "danger")
                return redirect(url_for("config.projects"))
            # 2) Fetch boards for project
            try:
                boards = jps.list_boards_for_project(project_key, pat)
            except JiraProjectsServiceError as exc:
                current_app.logger.warning(
                    "Board list failed eid=%s project=%s reason=%s",
                    current_user.eid, project_key, str(exc)
                )
                flash(str(exc), "danger")
                return redirect(url_for("config.projects"))
            # 3) NEW: Detect "Product Area" project key from board -> projects endpoint
            #    We stop at the first board that yields a Product Area category project.
            product_area_key = None
            try:
                for b in boards:
                    bid = int(b.get("board_id"))
                    pa = jps.get_product_area_project_key_for_board(bid, pat)
                    if pa:
                        product_area_key = pa
                        break
            except JiraProjectsServiceError as exc:
                # Non-fatal: we do not break add-project flow; we just log and proceed.
                current_app.logger.warning(
                    "Product Area key detection failed eid=%s project=%s reason=%s",
                    current_user.eid, project_key, str(exc)
                )
                product_area_key = None
            except Exception as exc:
                current_app.logger.exception(
                    "Unexpected Product Area key detection error eid=%s project=%s err=%s",
                    current_user.eid, project_key, exc
                )
                product_area_key = None
            # 4) Save project + boards
            try:
                proj = UserProject.query.filter_by(
                    user_id=current_user.id, project_key=project_key).first()
                if not proj:
                    proj = UserProjectx = UserProject(
                        user_id=current_user.id,
                        project_key=project_key,
                        admin_projects=True,
                    )
                    db.session.add(proj)
                    db.session.flush()
                else:
                    proj.admin_projects = True
                    # Clear boards so we re-sync with latest Jira list
                    UserBoard.query.filter_by(project_id=proj.id).delete()
                # Store Product Area key in user_projects (nullable)
                # Keep it uppercase for consistency
                proj.epic_key = (product_area_key or None)
                for b in boards:
                    db.session.add(
                        UserBoard(
                            project_id=proj.id,
                            board_id=b["board_id"],
                            board_name=b["board_name"],
                            board_type=b["board_type"],
                            board_url=b["board_url"],
                        )
                    )
                db.session.commit()
                current_app.logger.info(
                    "Project added eid=%s project=%s boards=%s product_area_key=%s",
                    current_user.eid, project_key, len(
                        boards), product_area_key
                )
                # Optional: include info message about Product Area capture (no failure if missing)
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
        # ------------------------------------------------------------------
        # Delete Project
        # ------------------------------------------------------------------
        if "delete_project" in request.form:
            if not delete_project_form.validate_on_submit():
                current_app.logger.warning(
                    "Delete project validation failed eid=%s errors=%s form=%s",
                    current_user.eid, delete_project_form.errors, dict(
                        request.form)
                )
                flash(
                    "Delete failed due to an invalid request (please refresh and try again).", "danger")
                return redirect(url_for("config.projects"))
            project_key = (
                delete_project_form.delete_project_key.data or "").strip().upper()
            try:
                removed = svc.delete_project(DeleteProjectRequest(
                    user_id=current_user.id, project_key=project_key))
                flash(
                    f"Project {project_key} deleted successfully (boards removed: {removed}).", "success")
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
        # ------------------------------------------------------------------
        # Delete Board
        # ------------------------------------------------------------------
        if "delete_board" in request.form:
            if not delete_board_form.validate_on_submit():
                current_app.logger.warning(
                    "Delete board validation failed eid=%s errors=%s form=%s",
                    current_user.eid, delete_board_form.errors, dict(
                        request.form)
                )
                flash(
                    "Delete failed due to an invalid request (please refresh and try again).", "danger")
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
                svc.delete_board(DeleteBoardRequest(
                    user_id=current_user.id,
                    project_key=project_key,
                    board_id=board_id
                ))
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
        # Reload after POST changes
        user_projects = (
            UserProject.query.filter_by(user_id=current_user.id)
            .order_by(UserProject.project_key.asc())
            .all()
        )
    return render_template(
        "config/projects_boards.html",
        project_form=project_form,
        delete_project_form=delete_project_form,
        delete_board_form=delete_board_form,
        user_projects=user_projects,
    )


@config_bp.route("/custom-views", methods=["GET", "POST"])
@login_required
def custom_views():
    custom_view_form = TableauCustomViewForm()
    delete_form = TableauCustomViewDeleteForm()
    # Load user's epic keys from DB (user_projects.epic_key)
    user_projects = (
        UserProject.query.filter_by(user_id=current_user.id)
        .order_by(UserProject.project_key.asc())
        .all()
    )
    # collect distinct epic_keys (non-empty)
    epic_keys = []
    seen = set()
    for p in user_projects:
        ek = (p.epic_key or "").strip().upper()
        if ek and ek not in seen:
            seen.add(ek)
            epic_keys.append(ek)
    # Populate dropdown strictly from DB
    custom_view_form.epic_key.choices = [(ek, ek) for ek in epic_keys]
    saved_custom_views = (
        UserTableauCustomView.query.filter_by(user_id=current_user.id)
        .order_by(UserTableauCustomView.updated_at.desc())
        .all()
    )
    if request.method == "POST":
        # -----------------------------
        # Add Custom View (mandatory epic_key mapping)
        # -----------------------------
        if "save_tableau_custom_view" in request.form:
            # If no epic keys exist, user cannot map → block
            if not epic_keys:
                flash(
                    "No Epic Keys found for your saved projects. Please add/refresh Projects & Boards so Epic Key is captured, then try again.",
                    "warning",
                )
                return redirect(url_for("config.custom_views"))
            if not custom_view_form.validate_on_submit():
                flash(
                    "Please select an Epic Key and provide a valid Custom View ID.", "danger")
                return redirect(url_for("config.custom_views"))
            epic_key = (custom_view_form.epic_key.data or "").strip().upper()
            custom_view_id = (
                custom_view_form.tableau_custom_view_id.data or "").strip()
            # validate epic_key is in DB-derived list
            if epic_key not in seen:
                flash(
                    "Invalid Epic Key selection. Please refresh and try again.", "danger")
                return redirect(url_for("config.custom_views"))
            # Existing guards (unchanged)
            if not getattr(current_user, "tableau_pat_name", None) or not getattr(current_user, "tableau_pat_secret_enc", None):
                flash(
                    "Please configure Tableau PAT first under Settings → Integrations.", "warning")
                return redirect(url_for("config.custom_views"))
            if not getattr(current_user, "tableau_site_id", None) or not getattr(current_user, "tableau_user_id", None):
                flash(
                    "Tableau identity is not saved. Please re-validate Tableau PAT under Settings → Integrations.", "warning")
                return redirect(url_for("config.custom_views"))
            try:
                pat_secret = _crypto().decrypt(current_user.tableau_pat_secret_enc)
            except Exception:
                flash(
                    "Unable to read saved Tableau PAT. Please re-save it under Settings → Integrations.", "danger")
                return redirect(url_for("config.integrations"))
            # Fetch view details (existing behavior)
            try:
                cv = _tableau_service().fetch_custom_view_details_by_id(
                    pat_name=current_user.tableau_pat_name,
                    pat_secret=pat_secret,
                    site_id=current_user.tableau_site_id,
                    custom_view_id=custom_view_id,
                )
            except TableauServiceError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("config.custom_views"))
            row = UserTableauCustomView.query.filter_by(
                user_id=current_user.id,
                custom_view_id=custom_view_id,
            ).first()
            if not row:
                row = UserTableauCustomView(
                    user_id=current_user.id, custom_view_id=custom_view_id)
                db.session.add(row)
            # Save epic_key mapping
            row.epic_key = epic_key
            # Existing metadata fields (keep unchanged)
            row.custom_view_name = cv.get("name")
            row.shared = cv.get("shared")
            view = cv.get("view") or {}
            workbook = cv.get("workbook") or {}
            row.view_id = view.get("id")
            row.view_name = view.get("name")
            row.workbook_id = workbook.get("id")
            row.workbook_name = workbook.get("name")
            db.session.commit()
            flash(
                f"Custom View saved and mapped to Epic Key: {epic_key}", "success")
            return redirect(url_for("config.custom_views"))
        # -----------------------------
        # Delete Custom View (unchanged)
        # -----------------------------
        if "delete_tableau_custom_view" in request.form:
            if not delete_form.validate_on_submit():
                flash(
                    "Delete failed due to an invalid request (please refresh and try again).", "danger")
                return redirect(url_for("config.custom_views"))
            delete_id = (delete_form.delete_custom_view_id.data or "").strip()
            row = UserTableauCustomView.query.filter_by(
                user_id=current_user.id, custom_view_id=delete_id).first()
            if not row:
                flash("Custom view not found.", "warning")
                return redirect(url_for("config.custom_views"))
            try:
                db.session.delete(row)
                db.session.commit()
                flash("Custom view deleted successfully.", "success")
            except Exception:
                db.session.rollback()
                flash("Failed to delete the custom view. Please check logs.", "danger")
            return redirect(url_for("config.custom_views"))
    # Reload list for GET / after POST
    saved_custom_views = (
        UserTableauCustomView.query.filter_by(user_id=current_user.id)
        .order_by(UserTableauCustomView.updated_at.desc())
        .all()
    )
    return render_template(
        "config/custom_views.html",
        tableau_custom_view_form=custom_view_form,
        tableau_custom_view_delete_form=delete_form,
        saved_custom_views=saved_custom_views,
    )
