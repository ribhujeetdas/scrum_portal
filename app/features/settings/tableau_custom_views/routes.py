from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from ....core.api import safe_error_message
from ....core.dependencies import crypto_service, tableau_service
from ....core.error_logging import log_handled_exception
from ....extensions import db
from ....models import UserProject, UserTableauCustomView
from ....services.tableau_service import TableauServiceError
from .forms import TableauCustomViewDeleteForm, TableauCustomViewForm


def _epic_key_choices() -> tuple[list[str], set[str]]:
    projects = (
        UserProject.query.filter_by(user_id=current_user.id)
        .order_by(UserProject.project_key.asc())
        .all()
    )
    epic_keys = []
    seen = set()
    for project in projects:
        epic_key = (project.epic_key or "").strip().upper()
        if epic_key and epic_key not in seen:
            seen.add(epic_key)
            epic_keys.append(epic_key)
    return epic_keys, seen


def custom_views_page():
    custom_view_form = TableauCustomViewForm()
    delete_form = TableauCustomViewDeleteForm()
    epic_keys, valid_epic_keys = _epic_key_choices()
    custom_view_form.epic_key.choices = [(epic_key, epic_key) for epic_key in epic_keys]

    if request.method == "POST":
        if "save_tableau_custom_view" in request.form:
            return _handle_save_custom_view(custom_view_form, epic_keys, valid_epic_keys)
        if "delete_tableau_custom_view" in request.form:
            return _handle_delete_custom_view(delete_form)

    return _render_custom_views(custom_view_form, delete_form)


def _handle_save_custom_view(
    custom_view_form: TableauCustomViewForm,
    epic_keys: list[str],
    valid_epic_keys: set[str],
):
    if not epic_keys:
        flash(
            "No Epic Keys found for your saved projects. Please add/refresh Projects & Boards so Epic Key is captured, then try again.",
            "warning",
        )
        return redirect(url_for("aliases.settings_tableau_custom_views"))

    if not custom_view_form.validate_on_submit():
        flash("Please select an Epic Key and provide a valid Custom View ID.", "danger")
        return redirect(url_for("aliases.settings_tableau_custom_views"))

    epic_key = (custom_view_form.epic_key.data or "").strip().upper()
    custom_view_id = (custom_view_form.tableau_custom_view_id.data or "").strip()

    if epic_key not in valid_epic_keys:
        flash("Invalid Epic Key selection. Please refresh and try again.", "danger")
        return redirect(url_for("aliases.settings_tableau_custom_views"))

    if not getattr(current_user, "tableau_pat_name", None) or not getattr(
        current_user, "tableau_pat_secret_enc", None
    ):
        flash("Please configure Tableau PAT first under Settings -> Integrations.", "warning")
        return redirect(url_for("aliases.settings_tableau_custom_views"))

    if not getattr(current_user, "tableau_site_id", None) or not getattr(
        current_user, "tableau_user_id", None
    ):
        flash(
            "Tableau identity is not saved. Please re-validate Tableau PAT under Settings -> Integrations.",
            "warning",
        )
        return redirect(url_for("aliases.settings_tableau_custom_views"))

    try:
        pat_secret = crypto_service().decrypt(current_user.tableau_pat_secret_enc)
    except Exception:
        flash(
            "Unable to read saved Tableau PAT. Please re-save it under Settings -> Integrations.",
            "danger",
        )
        return redirect(url_for("aliases.settings_integrations"))

    try:
        custom_view = tableau_service().fetch_custom_view_details_by_id(
            pat_name=current_user.tableau_pat_name,
            pat_secret=pat_secret,
            site_id=current_user.tableau_site_id,
            custom_view_id=custom_view_id,
        )
    except TableauServiceError as exc:
        log_handled_exception(
            "Tableau custom view validation failed",
            exc,
            event="settings.tableau_custom_views.validate_failed",
            feature="tableau_custom_view_settings",
            operation="validate_custom_view",
            context={"custom_view_id": custom_view_id, "epic_key": epic_key},
        )
        flash(safe_error_message("validate the Tableau custom view"), "danger")
        return redirect(url_for("aliases.settings_tableau_custom_views"))

    row = UserTableauCustomView.query.filter_by(
        user_id=current_user.id,
        custom_view_id=custom_view_id,
    ).first()
    if not row:
        row = UserTableauCustomView(
            user_id=current_user.id,
            custom_view_id=custom_view_id,
        )
        db.session.add(row)

    row.epic_key = epic_key
    row.custom_view_name = custom_view.get("name")
    row.shared = custom_view.get("shared")
    view = custom_view.get("view") or {}
    workbook = custom_view.get("workbook") or {}
    row.view_id = view.get("id")
    row.view_name = view.get("name")
    row.workbook_id = workbook.get("id")
    row.workbook_name = workbook.get("name")
    db.session.commit()

    flash(f"Custom View saved and mapped to Epic Key: {epic_key}", "success")
    return redirect(url_for("aliases.settings_tableau_custom_views"))


def _handle_delete_custom_view(delete_form: TableauCustomViewDeleteForm):
    if not delete_form.validate_on_submit():
        flash(
            "Delete failed due to an invalid request (please refresh and try again).",
            "danger",
        )
        return redirect(url_for("aliases.settings_tableau_custom_views"))

    delete_id = (delete_form.delete_custom_view_id.data or "").strip()
    row = UserTableauCustomView.query.filter_by(
        user_id=current_user.id,
        custom_view_id=delete_id,
    ).first()
    if not row:
        flash("Custom view not found.", "warning")
        return redirect(url_for("aliases.settings_tableau_custom_views"))

    try:
        db.session.delete(row)
        db.session.commit()
        flash("Custom view deleted successfully.", "success")
    except Exception:
        db.session.rollback()
        flash("Failed to delete the custom view. Please check logs.", "danger")
    return redirect(url_for("aliases.settings_tableau_custom_views"))


def _render_custom_views(
    custom_view_form: TableauCustomViewForm,
    delete_form: TableauCustomViewDeleteForm,
):
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
