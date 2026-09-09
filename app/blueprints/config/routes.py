"""Compatibility route registration for feature-owned settings handlers."""

from flask import redirect, url_for
from flask_login import login_required

from ...features.settings.integrations.routes import integrations_page
from ...features.settings.projects_boards.routes import projects_page
from ...features.settings.tableau_custom_views.routes import custom_views_page
from . import config_bp


@config_bp.route("/", methods=["GET"])
@login_required
def index():
    return redirect(url_for("aliases.settings_integrations"))


@config_bp.route("/integrations", methods=["GET", "POST"])
@login_required
def integrations():
    return integrations_page()


@config_bp.route("/projects", methods=["GET", "POST"])
@login_required
def projects():
    return projects_page()


@config_bp.route("/custom-views", methods=["GET", "POST"])
@login_required
def custom_views():
    return custom_views_page()
