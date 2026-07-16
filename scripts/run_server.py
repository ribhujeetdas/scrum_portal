from __future__ import annotations

import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from waitress import serve

from app import create_app
from app.core.config_validation import validate_config_or_raise
from app.core.database import application_database_lock, migration_status, sqlite_health
from app.features.automation.sprint_viewer.metric_jobs import get_sprint_metric_coordinator
from app.logging_conf import audit_event


def serve_app() -> None:
    app = create_app()
    validate_config_or_raise(app)

    with app.app_context():
        health = sqlite_health()
        expected_journal = str(app.config.get("SQLITE_JOURNAL_MODE", "DELETE")).lower()
        if health["journal_mode"] != expected_journal:
            raise RuntimeError(
                "SQLite journal mode does not match configuration: "
                f"expected={expected_journal}, actual={health['journal_mode']}. "
                "Run python scripts/database_configure.py while the server is stopped."
            )
        if not health["foreign_keys"]:
            raise RuntimeError("SQLite foreign-key enforcement is not active.")
        migrations = migration_status()
        if not migrations["current"]:
            raise RuntimeError(
                "Database migrations are not current: "
                f"current={migrations['current_heads']}, expected={migrations['expected_heads']}"
            )

    with application_database_lock(app):
        with app.app_context():
            metric_coordinator = get_sprint_metric_coordinator()
            metric_coordinator.recover()
        audit_event(
            "application.start",
            "Application server starting",
            application_version=app.config.get("APPLICATION_VERSION", "dev"),
            result="starting",
        )
        logging.getLogger("app.runtime").info(
            "Starting Waitress",
            extra={
                "event": "application.server.starting",
                "application_version": app.config.get("APPLICATION_VERSION", "dev"),
                "context": {
                    "host": app.config["WAITRESS_HOST"],
                    "port": app.config["WAITRESS_PORT"],
                    "threads": app.config["WAITRESS_THREADS"],
                    "connection_limit": app.config["WAITRESS_CONNECTION_LIMIT"],
                },
            },
        )
        try:
            serve(
                app,
                host=app.config["WAITRESS_HOST"],
                port=app.config["WAITRESS_PORT"],
                threads=app.config["WAITRESS_THREADS"],
                connection_limit=app.config["WAITRESS_CONNECTION_LIMIT"],
                channel_timeout=app.config["WAITRESS_CHANNEL_TIMEOUT_SECONDS"],
                max_request_body_size=app.config["MAX_CONTENT_LENGTH"],
                expose_tracebacks=False,
                clear_untrusted_proxy_headers=True,
            )
        finally:
            metric_coordinator.shutdown(wait=True)


def main() -> int:
    try:
        serve_app()
        return 0
    except KeyboardInterrupt:
        logging.getLogger("app.runtime").info(
            "Application server stopped",
            extra={"event": "application.server.stopped", "result": "success"},
        )
        return 0
    except Exception:
        logging.getLogger("app.runtime").exception(
            "Application server failed",
            extra={"event": "application.server.failed", "result": "failed"},
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
