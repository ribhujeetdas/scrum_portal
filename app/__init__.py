# app/__init__.py
from __future__ import annotations

from datetime import timedelta
from flask import Flask, render_template, request

from .config import Config
from .extensions import db, login_manager, csrf, migrate
from .logging_conf import configure_logging, init_request_correlation
from .core.config_validation import collect_config_warnings, log_config_warnings


def create_app(config_object: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)

    app.permanent_session_lifetime = timedelta(
        minutes=int(app.config.get("SESSION_TIMEOUT_MINUTES", 15))
    )

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)

    from . import models  # noqa: F401

    # Logging
    configure_logging(app)
    init_request_correlation(app)
    log_config_warnings(app, collect_config_warnings(app))

    # Blueprints
    from .blueprints.auth import auth_bp
    from .blueprints.main import main_bp
    from .blueprints.profile import profile_bp
    from .blueprints.config import config_bp
    from .blueprints.automation import automation_bp
    from .blueprints.tableau_custom_views import tableau_custom_views_bp
    from .blueprints.aliases import aliases_bp
    from .blueprints.aliases import routes as aliases_routes  # noqa: F401

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(automation_bp)
    app.register_blueprint(tableau_custom_views_bp)
    app.register_blueprint(aliases_bp)

    legacy_successors = {
        "/home": "/dashboard",
        "/login": "/auth/login",
        "/signup": "/auth/signup",
        "/forgot-password": "/auth/forgot-password",
        "/config/integrations": "/settings/integrations",
        "/config/projects": "/settings/projects-boards",
        "/config/custom-views": "/settings/tableau-custom-views",
        "/tableau/custom-views": "/reports/tci",
        "/session/status": "/api/session/status",
        "/session/extend": "/api/session/extend",
        "/client-log": "/api/client-log",
        "/automation/rule-copier/fetch-rule": "/api/automation/rule-copier/fetch",
        "/automation/rule-copier/copy-rule": "/api/automation/rule-copier/copy",
        "/automation/sprint-viewer/sprints": "/api/automation/sprint-viewer/sprints",
        "/automation/sprint-viewer/issues": "/api/automation/sprint-viewer/issues",
        "/automation/sprint-viewer/metrics": "/api/automation/sprint-viewer/metrics",
        "/tableau/custom-views/link-details": "/api/reports/tci/link-details",
    }

    @app.after_request
    def add_legacy_route_deprecation_headers(response):
        if not app.config.get("LEGACY_ROUTE_DEPRECATION_HEADERS", True):
            return response
        successor = legacy_successors.get(request.path)
        if not successor:
            return response
        response.headers["Deprecation"] = "true"
        response.headers["Link"] = f"<{successor}>; rel=\"successor-version\""
        sunset = str(app.config.get("LEGACY_ROUTE_SUNSET") or "").strip()
        if sunset:
            response.headers["Sunset"] = sunset
        return response

    # Error handlers
    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code=403, message="Forbidden"), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404, message="Not Found"), 404

    @app.errorhandler(500)
    def server_error(error):
        original = getattr(error, "original_exception", None) or error
        app.logger.error(
            "Unhandled server error",
            exc_info=(type(original), original, getattr(original, "__traceback__", None)),
            extra={"event": "error.unhandled"},
        )
        return render_template("error.html", code=500, message="Internal Server Error"), 500

    # CLI: init db
    @app.cli.command("init-db")
    def init_db_command():
        """Initialize the database."""
        with app.app_context():
            db.create_all()
        print("Database initialized.")

    return app
