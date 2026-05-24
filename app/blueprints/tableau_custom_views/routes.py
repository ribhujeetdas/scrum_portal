# app/blueprints/tableau_custom_views/routes.py
from __future__ import annotations

from flask_login import login_required

from ...features.reports.tci import routes as tci_feature
from . import tableau_custom_views_bp


@tableau_custom_views_bp.route("/custom-views", methods=["GET", "POST"])
@login_required
def custom_views_page():
    return tci_feature.custom_views_page()


@tableau_custom_views_bp.route("/custom-views/link-details", methods=["POST"])
@login_required
def custom_view_link_details():
    return tci_feature.custom_view_link_details()
