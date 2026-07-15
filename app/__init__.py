# app/__init__.py
from __future__ import annotations

from datetime import timedelta

from click import ClickException
from flask import Flask, make_response, render_template, request

from .config import CONFIG_BY_ENV, Config
from .core.api import json_error
from .core.config_validation import (
    collect_config_warnings,
    log_config_warnings,
    validate_config_or_raise,
)
from .core.database import configure_database
from .core.rate_limit import RateLimitExceeded, init_rate_limiter
from .core.security import init_security_headers
from .extensions import csrf, db, login_manager, migrate
from .logging_conf import configure_logging, init_request_correlation


def create_app(config_object: type[Config] | None = None) -> Flask:
    app = Flask(__name__)
    selected_config = config_object or CONFIG_BY_ENV.get(Config.APP_ENV, Config)
    app.config.from_object(selected_config)

    if app.config.get("APP_ENV") == "production" and not app.config.get("TESTING", False):
        validate_config_or_raise(app)

    app.permanent_session_lifetime = timedelta(
        minutes=int(app.config.get("SESSION_TIMEOUT_MINUTES", 15))
    )

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    init_rate_limiter(app)
    init_security_headers(app)

    from . import models  # noqa: F401

    configure_database(app)

    # Logging
    configure_logging(app)
    init_request_correlation(app)
    log_config_warnings(app, collect_config_warnings(app))

    # Blueprints
    from .blueprints.aliases import aliases_bp
    from .blueprints.aliases import routes as aliases_routes  # noqa: F401
    from .blueprints.auth import auth_bp
    from .blueprints.automation import automation_bp
    from .blueprints.config import config_bp
    from .blueprints.main import main_bp
    from .blueprints.profile import profile_bp
    from .blueprints.tableau_custom_views import tableau_custom_views_bp

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
        response.headers["Link"] = f'<{successor}>; rel="successor-version"'
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

    @app.errorhandler(RateLimitExceeded)
    def rate_limit_exceeded(error: RateLimitExceeded):
        app.logger.warning(
            "Request rate limited",
            extra={
                "event": "security.rate_limit.exceeded",
                "scope": error.scope,
                "retry_after": error.retry_after,
                "result": "rejected",
            },
        )
        if request.path.startswith("/api/") or request.is_json:
            response, status = json_error(
                "Too many requests. Please retry shortly.",
                status_code=429,
                code="rate_limited",
                details={"retry_after": error.retry_after},
            )
            response.headers["Retry-After"] = str(error.retry_after)
            return response, status
        else:
            response = make_response(
                render_template(
                    "error.html",
                    code=429,
                    message="Too many requests. Please retry shortly.",
                ),
                429,
            )
        response.headers["Retry-After"] = str(error.retry_after)
        return response

    # CLI: init db
    @app.cli.command("init-db")
    def init_db_command():
        """Reject the legacy unsafe initializer in favor of the migration runbook."""
        raise ClickException(
            "Use 'python scripts/migrate_db.py' so initialization, backup, and "
            "migration-head validation are applied consistently."
        )

    return app
