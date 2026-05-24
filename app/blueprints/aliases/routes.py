from __future__ import annotations

from . import aliases_bp
from ..auth.routes import (
    confirm_profile,
    forgot_password,
    login,
    logout,
    set_password,
    signup,
)
from ..automation.routes import (
    copy_rule,
    fetch_rule,
    sprint_viewer_fetch_issues,
    sprint_viewer_fetch_metrics,
    sprint_viewer_get_sprints,
)
from ..config.routes import custom_views, integrations, projects
from ..main.routes import client_log, extend_session, home, session_status
from ..tableau_custom_views.routes import custom_view_link_details, custom_views_page


# Canonical user-facing routes. Existing routes stay registered on their
# original blueprints, so bookmarks and current template URLs keep working.
aliases_bp.add_url_rule("/dashboard", "dashboard", home, methods=["GET"])
aliases_bp.add_url_rule("/auth/login", "auth_login", login, methods=["GET", "POST"])
aliases_bp.add_url_rule("/auth/signup", "auth_signup", signup, methods=["GET", "POST"])
aliases_bp.add_url_rule(
    "/auth/signup/confirm",
    "auth_signup_confirm",
    confirm_profile,
    methods=["GET", "POST"],
)
aliases_bp.add_url_rule(
    "/auth/signup/set-password",
    "auth_signup_set_password",
    set_password,
    methods=["GET", "POST"],
)
aliases_bp.add_url_rule(
    "/auth/forgot-password",
    "auth_forgot_password",
    forgot_password,
    methods=["GET"],
)
aliases_bp.add_url_rule("/auth/logout", "auth_logout", logout, methods=["POST"])

aliases_bp.add_url_rule(
    "/settings/integrations",
    "settings_integrations",
    integrations,
    methods=["GET", "POST"],
)
aliases_bp.add_url_rule(
    "/settings/projects-boards",
    "settings_projects_boards",
    projects,
    methods=["GET", "POST"],
)
aliases_bp.add_url_rule(
    "/settings/tableau-custom-views",
    "settings_tableau_custom_views",
    custom_views,
    methods=["GET", "POST"],
)

aliases_bp.add_url_rule("/reports/tci", "reports_tci", custom_views_page, methods=["GET", "POST"])


# Canonical API routes. They delegate to the existing view functions so behavior
# and authorization checks remain identical during migration.
aliases_bp.add_url_rule(
    "/api/automation/rule-copier/fetch",
    "api_rule_copier_fetch",
    fetch_rule,
    methods=["POST"],
)
aliases_bp.add_url_rule(
    "/api/automation/rule-copier/copy",
    "api_rule_copier_copy",
    copy_rule,
    methods=["POST"],
)
aliases_bp.add_url_rule(
    "/api/automation/sprint-viewer/sprints",
    "api_sprint_viewer_sprints",
    sprint_viewer_get_sprints,
    methods=["POST"],
)
aliases_bp.add_url_rule(
    "/api/automation/sprint-viewer/issues",
    "api_sprint_viewer_issues",
    sprint_viewer_fetch_issues,
    methods=["POST"],
)
aliases_bp.add_url_rule(
    "/api/automation/sprint-viewer/metrics",
    "api_sprint_viewer_metrics",
    sprint_viewer_fetch_metrics,
    methods=["POST"],
)
aliases_bp.add_url_rule(
    "/api/reports/tci/link-details",
    "api_reports_tci_link_details",
    custom_view_link_details,
    methods=["POST"],
)
aliases_bp.add_url_rule("/api/session/status", "api_session_status", session_status, methods=["GET"])
aliases_bp.add_url_rule("/api/session/extend", "api_session_extend", extend_session, methods=["POST"])
aliases_bp.add_url_rule("/api/client-log", "api_client_log", client_log, methods=["POST"])
