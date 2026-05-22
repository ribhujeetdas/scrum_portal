# app/blueprints/tableau_custom_views/routes.py
from __future__ import annotations

import csv
import io
from datetime import datetime, date

from flask import (
    current_app,
    render_template,
    flash,
    redirect,
    url_for,
    request,
    Response,
    jsonify,
)
from flask_login import login_required, current_user

from . import tableau_custom_views_bp
from .forms import TableauCustomViewSelectForm
from ...models import UserTableauCustomView
from ...services.crypto_service import CryptoService
from ...services.tableau_service import TableauService, TableauServiceError
from ...services.jira_issue_links_service import JiraIssueLinksService, JiraIssueLinksServiceError


def _crypto() -> CryptoService:
    return CryptoService(current_app.config["FERNET_KEY"])


def _tableau_service() -> TableauService:
    return TableauService(
        base_url=current_app.config.get("TABLEAU_BASE_URL", ""),
        api_version=current_app.config.get("TABLEAU_API_VERSION", "3.25"),
        site_content_url=current_app.config.get(
            "TABLEAU_SITE_CONTENT_URL", ""),
    )


def _jira_links_service() -> JiraIssueLinksService:
    return JiraIssueLinksService(current_app.config.get("JIRA_BASE_URL", ""))


def _get_user_jira_pat() -> str:
    if not current_user.jira_pat_enc:
        raise ValueError(
            "Enterprise Agile Jira PAT is not set. Please set it in Settings → Integrations.")
    return _crypto().decrypt(current_user.jira_pat_enc)


def _parse_date_tolerant(value: str):
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%b-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except Exception:
            continue
    return None


def _is_all(v: str) -> bool:
    return (v or "").strip().lower() == "all"


def _parse_csv_preview(csv_bytes: bytes, max_rows: int = 200) -> dict:
    """
    Preview rules:
    1) Only required columns.
    2) Drop rows where any key column is 'All':
       Application ID, Feature Issue Key, Planning Status, Start Date, Target End
    3) Sort by due date: upcoming soonest first; past dates at bottom
    4) Row-level flags:
       - Not Caught -> RED BLINK
       - Overdue (past) and status != Done -> OVERDUE BLINK (danger)
       - Due <= 31 days future and status != Done -> YELLOW BLINK
    """
    text = None
    for enc in ("utf-8-sig", "utf-16", "utf-16le"):
        try:
            text = csv_bytes.decode(enc)
            break
        except Exception:
            continue
    if text is None:
        text = csv_bytes.decode("latin-1", errors="replace")

    sample = text[:2000]
    dialect = csv.excel_tab if ("\t" in sample and sample.count(
        "\t") >= sample.count(",")) else csv.excel
    reader = csv.reader(io.StringIO(text), dialect)

    headers = []
    raw_rows = []
    for i, row in enumerate(reader):
        if i == 0:
            headers = row
            continue
        raw_rows.append(row)
        if len(raw_rows) >= max_rows:
            break

    cols = [
        "Application ID",
        "Feature Issue Key",
        "Planning Status",
        "Start Date",
        "Target End",
        "Due Date",
    ]
    idx = {c: headers.index(c) for c in cols if c in headers}

    # If any expected column missing, return minimal safe output
    missing = [c for c in cols if c not in idx]
    if missing:
        return {"headers": cols, "rows": [], "skipped_all": 0, "missing_columns": missing}

    today = date.today()
    rows = []
    skipped_all = 0

    for r in raw_rows:
        app_id = (r[idx["Application ID"]] or "").strip()
        feat_key = (r[idx["Feature Issue Key"]] or "").strip()
        plan = (r[idx["Planning Status"]] or "").strip()
        start = (r[idx["Start Date"]] or "").strip()
        target = (r[idx["Target End"]] or "").strip()
        due_raw = (r[idx["Due Date"]] or "").strip()

        # (1) Drop any 'All' in the specified metrics
        if _is_all(app_id) or _is_all(feat_key) or _is_all(plan) or _is_all(start) or _is_all(target):
            skipped_all += 1
            continue

        due_date = _parse_date_tolerant(due_raw)
        due_days = (due_date - today).days if due_date else None

        plan_l = plan.lower()
        is_done = (plan_l == "done")

        # Priority: Not Caught > Overdue > DueSoon
        row_red = (plan == "Not Caught")
        row_overdue = (not is_done) and (
            due_days is not None) and (due_days < 0)
        row_due_soon = (not is_done) and (
            due_days is not None) and (0 <= due_days <= 31)

        if row_red:
            row_class = "row-red-blink"
        elif row_overdue:
            row_class = "row-overdue-blink"
        elif row_due_soon:
            row_class = "row-yellow-blink"
        else:
            row_class = ""

        cells = [app_id, feat_key, plan, start, target, due_raw]

        rows.append(
            {
                "cells": cells,
                "row_class": row_class,
                "application_id": app_id,
                "feature_key": feat_key,
                "planning_status": plan,
                "due_days": due_days,
                "due_date_present": bool(due_date),
            }
        )

    # (2) Sort by due date
    def sort_key(item: dict):
        dd = item.get("due_days")
        if dd is None:
            # missing/invalid due date -> after future, before past
            return (1, 999999)
        if dd >= 0:
            return (0, dd)          # soonest first
        return (2, abs(dd))         # past at bottom, closest past first

    rows.sort(key=sort_key)

    return {"headers": cols, "rows": rows, "skipped_all": skipped_all, "missing_columns": []}


@tableau_custom_views_bp.route("/custom-views", methods=["GET", "POST"])
@login_required
def custom_views_page():
    # Existing guards from your implementation remain
    if not getattr(current_user, "tableau_pat_name", None) or not getattr(current_user, "tableau_pat_secret_enc", None):
        flash("Please configure Tableau PAT in Settings → Integrations first.", "warning")
        return redirect(url_for("config.integrations"))

    if not getattr(current_user, "tableau_site_id", None):
        flash("Tableau site identity not found. Please re-validate Tableau PAT.", "warning")
        return redirect(url_for("config.integrations"))

    rows = (
        UserTableauCustomView.query
        .filter_by(user_id=current_user.id)
        .order_by(
            UserTableauCustomView.custom_view_name.asc().nullslast(),
            UserTableauCustomView.custom_view_id.asc(),
        )
        .all()
    )

    if not rows:
        flash("No Tableau custom views saved yet. Add a Custom View ID in Settings → Tableau Custom Views.", "info")
        return redirect(url_for("config.custom_views"))

    form = TableauCustomViewSelectForm()
    form.custom_view_id.choices = [
        (r.custom_view_id, f"{r.custom_view_name or '(Unnamed)'}") for r in rows]

    preview = None
    selected_id = form.custom_view_id.data

    try:
        pat_secret = _crypto().decrypt(current_user.tableau_pat_secret_enc)
    except Exception:
        flash("Unable to read saved Tableau PAT. Please re-save it in Settings → Integrations.", "danger")
        return redirect(url_for("config.integrations"))

    if request.method == "POST" and form.validate_on_submit():
        selected_id = form.custom_view_id.data

        if "preview_data" in request.form or "download_csv" in request.form:
            try:
                signin = _tableau_service().sign_in_with_pat(
                    current_user.tableau_pat_name, pat_secret)
                token = signin["token"]
                try:
                    csv_bytes = _tableau_service().query_custom_view_data_csv(
                        token=token,
                        site_id=current_user.tableau_site_id,
                        custom_view_id=selected_id,
                        max_age_minutes=60,
                    )
                finally:
                    _tableau_service().sign_out(token)
            except TableauServiceError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("tableau_custom_views.custom_views_page"))

            if "download_csv" in request.form:
                return Response(
                    csv_bytes,
                    mimetype="text/csv",
                    headers={
                        "Content-Disposition": f'attachment; filename="{selected_id}.csv"'},
                )

            preview = _parse_csv_preview(csv_bytes, max_rows=200)

    return render_template(
        "tableau/custom_views.html",
        form=form,
        preview=preview,
        selected_custom_view_id=selected_id,
        jira_base_url=current_app.config.get("JIRA_BASE_URL", "").rstrip("/"),
    )


@tableau_custom_views_bp.route("/custom-views/link-details", methods=["POST"])
@login_required
def custom_view_link_details():
    payload = request.get_json(silent=True) or {}
    custom_view_id = (payload.get("custom_view_id") or "").strip()
    feature_key = (payload.get("feature_key") or "").strip()
    application_id = (payload.get("application_id") or "").strip()

    if not custom_view_id or not feature_key or not application_id:
        return jsonify({"ok": False, "error": "custom_view_id, feature_key, and application_id are required."}), 400

    # Lookup mapping for this custom view (use epic_key if you implemented epic mapping; fallback to project_key if present)
    row = UserTableauCustomView.query.filter_by(
        user_id=current_user.id, custom_view_id=custom_view_id).first()
    if not row:
        return jsonify({"ok": False, "error": "Custom view mapping not found for this user."}), 404

    mapped_key = (getattr(row, "epic_key", None) or getattr(
        row, "project_key", None) or "").strip().upper()
    if not mapped_key:
        return jsonify({"ok": False, "error": "No mapped key (epic_key/project_key) saved for this Custom View. Please map it in Settings."}), 400

    try:
        pat = _get_user_jira_pat()
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403

    try:
        result = _jira_links_service().validate_related_ticket(
            feature_key=feature_key,
            mapped_key=mapped_key,
            application_id=application_id,
            pat=pat,
        )
        return jsonify(
            {
                "ok": True,
                "feature_key": result.feature_key,
                "mapped_key": result.mapped_key,
                "application_id": result.application_id,
                "message": result.message,
                "matches": result.matches,
            }
        )
    except JiraIssueLinksServiceError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        current_app.logger.exception(
            "Unexpected error in custom_view_link_details")
        return jsonify({"ok": False, "error": "Unexpected error occurred."}), 500
