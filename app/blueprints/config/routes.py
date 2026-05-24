# app/blueprints/config/routes.py
from __future__ import annotations

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ...core.api import safe_error_message
from ...core.dependencies import crypto_service, jira_service, tableau_service
from ...core.error_logging import log_handled_exception
from ...extensions import db
from ...features.settings.projects_boards.routes import projects_page
from ...features.settings.tableau_custom_views.routes import custom_views_page
from ...services.jira_service import JiraServiceError
from ...services.tableau_service import TableauServiceError
from . import config_bp
from .forms import JiraConfigForm, TableauConfigForm


def _masked_jira_token() -> str:
    if not current_user.jira_pat_enc:
        return "Not set"
    try:
        pat = crypto_service().decrypt(current_user.jira_pat_enc)
        return ("*" * max(0, len(pat) - 4)) + pat[-4:]
    except Exception:
        return "******"


def _masked_tableau_secret() -> str:
    if not getattr(current_user, "tableau_pat_secret_enc", None):
        return "Not set"
    try:
        secret = crypto_service().decrypt(current_user.tableau_pat_secret_enc)
        return ("*" * max(0, len(secret) - 4)) + secret[-4:]
    except Exception:
        return "******"


@config_bp.route("/", methods=["GET"])
@login_required
def index():
    return redirect(url_for("aliases.settings_integrations"))


@config_bp.route("/integrations", methods=["GET", "POST"])
@login_required
def integrations():
    pat_form = JiraConfigForm()
    tableau_form = TableauConfigForm()
    masked_token = _masked_jira_token()
    masked_tableau_token = _masked_tableau_secret()
    tableau_pat_name_saved = getattr(current_user, "tableau_pat_name", None) or ""

    if request.method == "POST":
        if "validate_and_save" in request.form and pat_form.validate_on_submit():
            return _save_jira_pat(pat_form)

        if (
            "tableau_validate_and_save" in request.form
            and tableau_form.validate_on_submit()
        ):
            return _save_tableau_pat(tableau_form)

    return render_template(
        "config/integrations.html",
        pat_form=pat_form,
        tableau_form=tableau_form,
        masked_token=masked_token,
        masked_tableau_token=masked_tableau_token,
        tableau_pat_name_saved=tableau_pat_name_saved,
    )


def _save_jira_pat(pat_form: JiraConfigForm):
    pat_input = (pat_form.jira_pat.data or "").strip()
    try:
        profile_json = jira_service().fetch_myself(pat_input)
    except JiraServiceError as exc:
        log_handled_exception(
            "Jira PAT validation failed",
            exc,
            event="settings.integrations.jira_pat_validate_failed",
            feature="integrations",
            operation="validate_jira_pat",
            context={"eid": current_user.eid, "email": current_user.email},
        )
        flash(safe_error_message("validate Jira PAT"), "danger")
        return redirect(url_for("aliases.settings_integrations"))

    api_email = (profile_json.get("emailAddress") or "").strip()
    active = bool(profile_json.get("active"))
    deleted = bool(profile_json.get("deleted"))
    if api_email.lower() != current_user.email.lower():
        flash("Token belongs to a different user (email mismatch).", "danger")
        return redirect(url_for("aliases.settings_integrations"))
    if not active or deleted:
        flash("Jira profile is not active or is deleted.", "danger")
        return redirect(url_for("aliases.settings_integrations"))

    current_user.jira_pat_enc = crypto_service().encrypt(pat_input)
    db.session.commit()
    current_app.logger.info(
        "User updated Jira PAT eid=%s email=%s", current_user.eid, current_user.email
    )
    flash("Token validated and saved successfully.", "success")
    return redirect(url_for("aliases.settings_integrations"))


def _save_tableau_pat(tableau_form: TableauConfigForm):
    pat_name = (tableau_form.tableau_pat_name.data or "").strip()
    pat_secret = (tableau_form.tableau_pat_secret.data or "").strip()
    try:
        identity = tableau_service().validate_pat_and_get_identity(pat_name, pat_secret)
    except (TableauServiceError, ValueError) as exc:
        log_handled_exception(
            "Tableau PAT validation failed",
            exc,
            event="settings.integrations.tableau_pat_validate_failed",
            feature="integrations",
            operation="validate_tableau_pat",
            context={"eid": current_user.eid, "email": current_user.email},
        )
        flash(safe_error_message("validate Tableau PAT"), "danger")
        return redirect(url_for("aliases.settings_integrations"))
    except Exception as exc:
        current_app.logger.exception("Unexpected Tableau validation error: %s", exc)
        flash("Unexpected error occurred while validating Tableau PAT.", "danger")
        return redirect(url_for("aliases.settings_integrations"))

    tableau_email = (identity.get("email") or "").strip()
    tableau_eid = (identity.get("eid") or "").strip()
    if tableau_email.lower() != current_user.email.lower():
        flash(
            f"Tableau user email '{tableau_email}' does not match your registered email '{current_user.email}'.",
            "danger",
        )
        return redirect(url_for("aliases.settings_integrations"))
    if tableau_eid.lower() != current_user.eid.lower():
        flash(
            f"Tableau user name/EID '{tableau_eid}' does not match your registered EID '{current_user.eid}'.",
            "danger",
        )
        return redirect(url_for("aliases.settings_integrations"))

    current_user.tableau_pat_name = pat_name
    current_user.tableau_pat_secret_enc = crypto_service().encrypt(pat_secret)
    current_user.tableau_site_id = identity.get("site_id")
    current_user.tableau_user_id = identity.get("user_id")
    current_user.tableau_content_url = identity.get("content_url")
    current_user.tableau_email = tableau_email
    current_user.tableau_eid = tableau_eid
    db.session.commit()
    current_app.logger.info(
        "User updated Tableau PAT eid=%s email=%s",
        current_user.eid,
        current_user.email,
    )
    flash("Tableau PAT validated and saved successfully.", "success")
    return redirect(url_for("aliases.settings_integrations"))


@config_bp.route("/projects", methods=["GET", "POST"])
@login_required
def projects():
    return projects_page()


@config_bp.route("/custom-views", methods=["GET", "POST"])
@login_required
def custom_views():
    return custom_views_page()
