# app/__init__.py
from __future__ import annotations

from datetime import timedelta
from flask import Flask, jsonify, redirect, render_template, request, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_login import current_user

from .config import Config
from .extensions import db, login_manager, csrf, migrate
from .logging_conf import configure_logging, init_request_correlation
from .core.config_validation import collect_config_warnings, log_config_warnings
from .core.config_validation import validate_startup_config
from .core.database import configure_database, enable_and_verify_wal
from .core.security import enforce_server_session
from .core.commands import register_commands
from .core.health import register_health_routes
from .core.rate_limits import enforce_rate_limit
from .core.dependencies import close_request_services


def create_app(config_object: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)
    proxy_count = int(app.config.get("TRUSTED_PROXY_COUNT", 0))
    if proxy_count > 0:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=proxy_count,
            x_proto=proxy_count,
            x_host=proxy_count,
        )
    configure_database(app)
    validate_startup_config(app)

    app.permanent_session_lifetime = timedelta(
        minutes=int(app.config.get("SESSION_TIMEOUT_MINUTES", 15))
    )

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.unauthorized_handler
    def unauthorized():
        if (
            request.path.startswith("/api/")
            or request.path.startswith("/automation/sprint-viewer/")
            or request.is_json
        ):
            return jsonify({
                "ok": False,
                "error": {
                    "code": "AUTHENTICATION_REQUIRED",
                    "message": "Authentication is required.",
                },
            }), 401
        return redirect(url_for("aliases.auth_login", next=request.url))

    csrf.init_app(app)
    migrate.init_app(app, db)

    from . import models  # noqa: F401

    with app.app_context():
        if app.config.get("APP_ENV") == "production" or app.config.get("ENABLE_SQLITE_WAL", False):
            enable_and_verify_wal(app, db.engine)

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

    @app.before_request
    def enforce_control_api_body_limit():
        if request.method not in {"POST", "PUT", "PATCH"} or not request.is_json:
            return None
        if request.path.endswith(("/client-log", "/client_log", "/rule-copier/copy", "/rule-copier/copy-rule")):
            return None
        if len(request.get_data(cache=True)) <= 64 * 1024:
            return None
        return jsonify({
            "ok": False,
            "error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body is too large."},
        }), 413

    app.before_request(enforce_server_session)
    app.before_request(enforce_rate_limit)
    register_commands(app)
    register_health_routes(app)
    app.teardown_request(close_request_services)

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
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if app.config.get("APP_ENV") == "production" and request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if current_user.is_authenticated and not request.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "no-store")
        if request.path.startswith("/api/") or request.path.startswith("/automation/sprint-viewer/"):
            response.headers.setdefault("Cache-Control", "no-store")
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
        """Deprecated unsafe entry point."""
        raise RuntimeError("init-db is retired; use 'flask setup-db --apply'")

    return app
