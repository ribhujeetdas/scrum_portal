# app/__init__.py
from __future__ import annotations

from datetime import timedelta
from flask import Flask, render_template

from .config import Config
from .extensions import db, login_manager, csrf, migrate
from .logging_conf import configure_logging, init_request_correlation


def create_app(config_object: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)

    # 30-minute session expiry
    app.permanent_session_lifetime = timedelta(minutes=30)

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)

    from . import models  # noqa: F401

    # Logging
    configure_logging(app)
    init_request_correlation(app)

    # Blueprints
    from .blueprints.auth import auth_bp
    from .blueprints.main import main_bp
    from .blueprints.profile import profile_bp
    from .blueprints.config import config_bp
    from .blueprints.automation import automation_bp
    from .blueprints.tableau_custom_views import tableau_custom_views_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(automation_bp)
    app.register_blueprint(tableau_custom_views_bp)

    # Error handlers
    @app.errorhandler(403)
    def forbidden(_):
        return render_template("error.html", code=403, message="Forbidden"), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404, message="Not Found"), 404

    @app.errorhandler(500)
    def server_error(_):
        return render_template("error.html", code=500, message="Internal Server Error"), 500

    # CLI: init db
    @app.cli.command("init-db")
    def init_db_command():
        """Initialize the database."""
        with app.app_context():
            db.create_all()
        print("Database initialized.")

    return app
