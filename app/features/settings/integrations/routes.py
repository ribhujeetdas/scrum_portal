from __future__ import annotations

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ....blueprints.config.forms import JiraConfigForm, TableauConfigForm
from ....core.api import safe_error_message
from ....core.dependencies import crypto_service, jira_service, tableau_service
from ....core.error_logging import log_handled_exception
from ....core.security import invalidate_user_access
from ....extensions import db
from ....services.jira_service import JiraServiceError
from ....services.tableau_service import TableauServiceError


def _masked_secret(encrypted_value) -> str:
    if not encrypted_value:
        return "Not set"
    try:
        value = crypto_service().decrypt(encrypted_value)
        return ("*" * max(0, len(value) - 4)) + value[-4:]
    except Exception:
        return "******"


def integrations_page():
    pat_form = JiraConfigForm()
    tableau_form = TableauConfigForm()
    if request.method == "POST":
        if "validate_and_save" in request.form and pat_form.validate_on_submit():
            return save_jira_pat(pat_form)
        if "tableau_validate_and_save" in request.form and tableau_form.validate_on_submit():
            return save_tableau_pat(tableau_form)
    return render_template(
        "config/integrations.html",
        pat_form=pat_form,
        tableau_form=tableau_form,
        masked_token=_masked_secret(current_user.jira_pat_enc),
        masked_tableau_token=_masked_secret(current_user.tableau_pat_secret_enc),
        tableau_pat_name_saved=current_user.tableau_pat_name or "",
    )


def save_jira_pat(pat_form: JiraConfigForm):
    pat_input = (pat_form.jira_pat.data or "").strip()
    try:
        profile = jira_service().fetch_myself(pat_input)
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
    api_email = str(profile.get("emailAddress") or "").strip()
    if api_email.casefold() != current_user.email.casefold():
        flash("Token belongs to a different user (email mismatch).", "danger")
        return redirect(url_for("aliases.settings_integrations"))
    if not profile.get("active") or profile.get("deleted"):
        flash("Jira profile is not active or is deleted.", "danger")
        return redirect(url_for("aliases.settings_integrations"))
    current_user.jira_pat_enc = crypto_service().encrypt(pat_input)
    invalidate_user_access(current_user, credentials_changed=True)
    db.session.commit()
    current_app.logger.info("User updated Jira PAT eid=%s", current_user.eid)
    flash("Token validated and saved successfully.", "success")
    return redirect(url_for("aliases.settings_integrations"))


def save_tableau_pat(tableau_form: TableauConfigForm):
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
    except Exception:
        current_app.logger.exception("Unexpected Tableau validation error")
        flash("Unexpected error occurred while validating Tableau PAT.", "danger")
        return redirect(url_for("aliases.settings_integrations"))
    tableau_email = str(identity.get("email") or "").strip()
    tableau_eid = str(identity.get("eid") or "").strip()
    if tableau_email.casefold() != current_user.email.casefold():
        flash("Tableau user email does not match your registered email.", "danger")
        return redirect(url_for("aliases.settings_integrations"))
    if tableau_eid.casefold() != current_user.eid.casefold():
        flash("Tableau user name/EID does not match your registered EID.", "danger")
        return redirect(url_for("aliases.settings_integrations"))
    current_user.tableau_pat_name = pat_name
    current_user.tableau_pat_secret_enc = crypto_service().encrypt(pat_secret)
    current_user.tableau_site_id = identity.get("site_id")
    current_user.tableau_user_id = identity.get("user_id")
    current_user.tableau_content_url = identity.get("content_url")
    current_user.tableau_email = tableau_email
    current_user.tableau_eid = tableau_eid
    db.session.commit()
    current_app.logger.info("User updated Tableau PAT eid=%s", current_user.eid)
    flash("Tableau PAT validated and saved successfully.", "success")
    return redirect(url_for("aliases.settings_integrations"))
