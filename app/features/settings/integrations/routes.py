from __future__ import annotations

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ....core.api import safe_error_message
from ....core.database import execute_write
from ....core.dependencies import crypto_service, jira_service, tableau_service
from ....core.error_logging import log_handled_exception
from ....core.rate_limit import enforce_limit
from ....logging_conf import audit_event
from ....services.jira_service import JiraServiceError
from ....services.tableau_service import TableauServiceError
from .forms import JiraConfigForm, TableauConfigForm


def _audit_credential_rejected(service: str, reason: str) -> None:
    audit_event(
        f"settings.integrations.{service}_pat.rejected",
        f"{service.title()} credential update rejected",
        resource_type="user_integration",
        resource_id=str(current_user.id),
        result=reason,
    )


def _masked_jira_token() -> str:
    if not current_user.jira_pat_enc:
        return "Not set"
    try:
        pat = crypto_service().decrypt(current_user.jira_pat_enc)
        return ("*" * max(0, len(pat) - 4)) + pat[-4:]
    except (TypeError, ValueError):
        return "******"


def _masked_tableau_secret() -> str:
    if not getattr(current_user, "tableau_pat_secret_enc", None):
        return "Not set"
    try:
        secret = crypto_service().decrypt(current_user.tableau_pat_secret_enc)
        return ("*" * max(0, len(secret) - 4)) + secret[-4:]
    except (TypeError, ValueError):
        return "******"


def integrations_page():
    pat_form = JiraConfigForm()
    tableau_form = TableauConfigForm()
    if request.method == "POST":
        enforce_limit("settings.integrations.update", subject=str(current_user.id), expensive=True)
        if "validate_and_save" in request.form and pat_form.validate_on_submit():
            return _save_jira_pat(pat_form)
        if "tableau_validate_and_save" in request.form and tableau_form.validate_on_submit():
            return _save_tableau_pat(tableau_form)

    return render_template(
        "config/integrations.html",
        pat_form=pat_form,
        tableau_form=tableau_form,
        masked_token=_masked_jira_token(),
        masked_tableau_token=_masked_tableau_secret(),
        tableau_pat_name_saved=getattr(current_user, "tableau_pat_name", None) or "",
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
            context={"user_id": current_user.id},
        )
        _audit_credential_rejected("jira", "validation_failed")
        flash(safe_error_message("validate Jira PAT"), "danger")
        return redirect(url_for("aliases.settings_integrations"))

    api_email = (profile_json.get("emailAddress") or "").strip()
    if api_email.lower() != current_user.email.lower():
        _audit_credential_rejected("jira", "identity_mismatch")
        flash("Token belongs to a different user (email mismatch).", "danger")
        return redirect(url_for("aliases.settings_integrations"))
    if not bool(profile_json.get("active")) or bool(profile_json.get("deleted")):
        _audit_credential_rejected("jira", "inactive_identity")
        flash("Jira profile is not active or is deleted.", "danger")
        return redirect(url_for("aliases.settings_integrations"))

    encrypted = crypto_service().encrypt(pat_input)

    def persist() -> None:
        current_user.jira_pat_enc = encrypted

    execute_write(persist)
    current_app.logger.info(
        "User updated Jira PAT",
        extra={"event": "settings.integrations.jira_pat.updated", "result": "success"},
    )
    audit_event(
        "settings.integrations.jira_pat.updated",
        "Jira credential updated",
        resource_type="user_integration",
        resource_id=str(current_user.id),
        result="success",
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
            context={"user_id": current_user.id},
        )
        _audit_credential_rejected("tableau", "validation_failed")
        flash(safe_error_message("validate Tableau PAT"), "danger")
        return redirect(url_for("aliases.settings_integrations"))

    tableau_email = (identity.get("email") or "").strip()
    tableau_eid = (identity.get("eid") or "").strip()
    if tableau_email.lower() != current_user.email.lower():
        _audit_credential_rejected("tableau", "email_mismatch")
        flash("Tableau identity does not match your registered email.", "danger")
        return redirect(url_for("aliases.settings_integrations"))
    if tableau_eid.lower() != current_user.eid.lower():
        _audit_credential_rejected("tableau", "eid_mismatch")
        flash("Tableau identity does not match your registered EID.", "danger")
        return redirect(url_for("aliases.settings_integrations"))

    encrypted = crypto_service().encrypt(pat_secret)

    def persist() -> None:
        current_user.tableau_pat_name = pat_name
        current_user.tableau_pat_secret_enc = encrypted
        current_user.tableau_site_id = identity.get("site_id")
        current_user.tableau_user_id = identity.get("user_id")
        current_user.tableau_content_url = identity.get("content_url")
        current_user.tableau_email = tableau_email
        current_user.tableau_eid = tableau_eid

    execute_write(persist)
    current_app.logger.info(
        "User updated Tableau PAT",
        extra={
            "event": "settings.integrations.tableau_pat.updated",
            "result": "success",
        },
    )
    audit_event(
        "settings.integrations.tableau_pat.updated",
        "Tableau credential updated",
        resource_type="user_integration",
        resource_id=str(current_user.id),
        result="success",
    )
    flash("Tableau PAT validated and saved successfully.", "success")
    return redirect(url_for("aliases.settings_integrations"))
