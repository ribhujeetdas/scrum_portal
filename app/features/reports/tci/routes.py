from __future__ import annotations

import csv
import io
from datetime import date, datetime

from flask import Response, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ....core.api import json_error, json_ok
from ....core.dependencies import crypto_service, jira_issue_links_service, tableau_service
from ....models import UserTableauCustomView
from ....services.jira_issue_links_service import JiraIssueLinksServiceError
from ....services.tableau_service import TableauServiceError
from .forms import TableauCustomViewSelectForm


def _get_user_jira_pat() -> str:
    if not current_user.jira_pat_enc:
        raise ValueError(
            "Enterprise Agile Jira PAT is not set. Please set it in Settings -> Integrations."
        )
    return crypto_service().decrypt(current_user.jira_pat_enc)


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


def _is_all(value: str) -> bool:
    return (value or "").strip().lower() == "all"


def parse_csv_preview(csv_bytes: bytes, max_rows: int = 200) -> dict:
    text = None
    for encoding in ("utf-8-sig", "utf-16", "utf-16le"):
        try:
            text = csv_bytes.decode(encoding)
            break
        except Exception:
            continue
    if text is None:
        text = csv_bytes.decode("latin-1", errors="replace")

    sample = text[:2000]
    dialect = (
        csv.excel_tab
        if "\t" in sample and sample.count("\t") >= sample.count(",")
        else csv.excel
    )
    reader = csv.reader(io.StringIO(text), dialect)

    headers = []
    raw_rows = []
    for row_index, row in enumerate(reader):
        if row_index == 0:
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
    idx = {column: headers.index(column) for column in cols if column in headers}

    missing = [column for column in cols if column not in idx]
    if missing:
        return {"headers": cols, "rows": [], "skipped_all": 0, "missing_columns": missing}

    today = date.today()
    rows = []
    skipped_all = 0

    for raw_row in raw_rows:
        app_id = (raw_row[idx["Application ID"]] or "").strip()
        feat_key = (raw_row[idx["Feature Issue Key"]] or "").strip()
        plan = (raw_row[idx["Planning Status"]] or "").strip()
        start = (raw_row[idx["Start Date"]] or "").strip()
        target = (raw_row[idx["Target End"]] or "").strip()
        due_raw = (raw_row[idx["Due Date"]] or "").strip()

        if (
            _is_all(app_id)
            or _is_all(feat_key)
            or _is_all(plan)
            or _is_all(start)
            or _is_all(target)
        ):
            skipped_all += 1
            continue

        due_date = _parse_date_tolerant(due_raw)
        due_days = (due_date - today).days if due_date else None
        is_done = plan.lower() == "done"

        row_red = plan == "Not Caught"
        row_overdue = not is_done and due_days is not None and due_days < 0
        row_due_soon = not is_done and due_days is not None and 0 <= due_days <= 31

        if row_red:
            row_class = "row-red-blink"
        elif row_overdue:
            row_class = "row-overdue-blink"
        elif row_due_soon:
            row_class = "row-yellow-blink"
        else:
            row_class = ""

        rows.append(
            {
                "cells": [app_id, feat_key, plan, start, target, due_raw],
                "row_class": row_class,
                "application_id": app_id,
                "feature_key": feat_key,
                "planning_status": plan,
                "due_days": due_days,
                "due_date_present": bool(due_date),
            }
        )

    def sort_key(item: dict):
        due_days = item.get("due_days")
        if due_days is None:
            return (1, 999999)
        if due_days >= 0:
            return (0, due_days)
        return (2, abs(due_days))

    rows.sort(key=sort_key)

    return {"headers": cols, "rows": rows, "skipped_all": skipped_all, "missing_columns": []}


def custom_views_page():
    if not getattr(current_user, "tableau_pat_name", None) or not getattr(
        current_user, "tableau_pat_secret_enc", None
    ):
        flash("Please configure Tableau PAT in Settings -> Integrations first.", "warning")
        return redirect(url_for("config.integrations"))

    if not getattr(current_user, "tableau_site_id", None):
        flash("Tableau site identity not found. Please re-validate Tableau PAT.", "warning")
        return redirect(url_for("config.integrations"))

    rows = (
        UserTableauCustomView.query.filter_by(user_id=current_user.id)
        .order_by(
            UserTableauCustomView.custom_view_name.asc().nullslast(),
            UserTableauCustomView.custom_view_id.asc(),
        )
        .all()
    )

    if not rows:
        flash(
            "No Tableau custom views saved yet. Add a Custom View ID in Settings -> Tableau Custom Views.",
            "info",
        )
        return redirect(url_for("config.custom_views"))

    form = TableauCustomViewSelectForm()
    form.custom_view_id.choices = [
        (row.custom_view_id, f"{row.custom_view_name or '(Unnamed)'}") for row in rows
    ]

    preview = None
    selected_id = form.custom_view_id.data

    try:
        pat_secret = crypto_service().decrypt(current_user.tableau_pat_secret_enc)
    except Exception:
        flash(
            "Unable to read saved Tableau PAT. Please re-save it in Settings -> Integrations.",
            "danger",
        )
        return redirect(url_for("config.integrations"))

    if request.method == "POST" and form.validate_on_submit():
        selected_id = form.custom_view_id.data

        if "preview_data" in request.form or "download_csv" in request.form:
            try:
                signin = tableau_service().sign_in_with_pat(
                    current_user.tableau_pat_name, pat_secret
                )
                token = signin["token"]
                try:
                    csv_bytes = tableau_service().query_custom_view_data_csv(
                        token=token,
                        site_id=current_user.tableau_site_id,
                        custom_view_id=selected_id,
                        max_age_minutes=60,
                    )
                finally:
                    tableau_service().sign_out(token)
            except TableauServiceError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("tableau_custom_views.custom_views_page"))

            if "download_csv" in request.form:
                return Response(
                    csv_bytes,
                    mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{selected_id}.csv"'},
                )

            preview = parse_csv_preview(csv_bytes, max_rows=200)

    return render_template(
        "tableau/custom_views.html",
        form=form,
        preview=preview,
        selected_custom_view_id=selected_id,
        jira_base_url=current_app.config.get("JIRA_BASE_URL", "").rstrip("/"),
    )


def custom_view_link_details():
    payload = request.get_json(silent=True) or {}
    custom_view_id = (payload.get("custom_view_id") or "").strip()
    feature_key = (payload.get("feature_key") or "").strip()
    application_id = (payload.get("application_id") or "").strip()

    if not custom_view_id or not feature_key or not application_id:
        return json_error(
            "custom_view_id, feature_key, and application_id are required.",
            status_code=400,
        )

    row = UserTableauCustomView.query.filter_by(
        user_id=current_user.id, custom_view_id=custom_view_id
    ).first()
    if not row:
        return json_error("Custom view mapping not found for this user.", status_code=404)

    mapped_key = (
        getattr(row, "epic_key", None) or getattr(row, "project_key", None) or ""
    ).strip().upper()
    if not mapped_key:
        return json_error(
            "No mapped key (epic_key/project_key) saved for this Custom View. Please map it in Settings.",
            status_code=400,
        )

    try:
        pat = _get_user_jira_pat()
    except Exception as exc:
        return json_error(str(exc), status_code=403)

    try:
        result = jira_issue_links_service().validate_related_ticket(
            feature_key=feature_key,
            mapped_key=mapped_key,
            application_id=application_id,
            pat=pat,
        )
        return json_ok(
            feature_key=result.feature_key,
            mapped_key=result.mapped_key,
            application_id=result.application_id,
            message=result.message,
            matches=result.matches,
        )
    except JiraIssueLinksServiceError as exc:
        return json_error(str(exc), status_code=400)
    except Exception:
        current_app.logger.exception("Unexpected error in custom_view_link_details")
        return json_error("Unexpected error occurred.", status_code=500)
