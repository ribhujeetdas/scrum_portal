from __future__ import annotations

from datetime import UTC, datetime

from flask import Flask, current_app, jsonify
from sqlalchemy import text

from ..extensions import db
from ..features.automation.sprint_viewer.models import WorkerLeader


SCHEMA_HEAD = "b27d5f8a9c02"


def _age_seconds(value) -> float:
    if value is None: return float("inf")
    if value.tzinfo is None: value = value.replace(tzinfo=UTC)
    return (datetime.now(UTC) - value).total_seconds()


def register_health_routes(app: Flask) -> None:
    def live():
        return jsonify({"ok": True, "status": "live"})

    def ready():
        try:
            db.session.execute(text("SELECT 1")).scalar_one()
            revision = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if revision != SCHEMA_HEAD:
                raise RuntimeError("Database schema is not at the application head")
            if db.engine.dialect.name == "sqlite" and db.engine.url.database != ":memory:":
                if str(db.session.execute(text("PRAGMA journal_mode")).scalar()).lower() != "wal":
                    raise RuntimeError("WAL is not active")
            worker_required = current_app.config.get("SPRINT_VIEWER_MODE") == "snapshot"
            leader = db.session.get(WorkerLeader, "sprint-worker") if worker_required else None
            worker_ready = not worker_required or (
                leader is not None and _age_seconds(leader.last_heartbeat) <= int(current_app.config["SPRINT_WORKER_STALE_SECONDS"])
            )
            if not worker_ready:
                return jsonify({"ok": False, "status": "not_ready", "worker": "stale"}), 503
            return jsonify({"ok": True, "status": "ready", "worker": "ready" if worker_required else "not_required"})
        except Exception:
            db.session.rollback()
            return jsonify({"ok": False, "status": "not_ready"}), 503

    def worker():
        try:
            leader = db.session.get(WorkerLeader, "sprint-worker")
            ready_value = bool(leader and _age_seconds(leader.last_heartbeat) <= int(current_app.config["SPRINT_WORKER_STALE_SECONDS"]))
            return jsonify({"ok": ready_value, "status": "ready" if ready_value else "stale"}), (200 if ready_value else 503)
        except Exception:
            return jsonify({"ok": False, "status": "unavailable"}), 503

    app.add_url_rule("/health/live", "health_live", live, methods=["GET"])
    app.add_url_rule("/health/ready", "health_ready", ready, methods=["GET"])
    app.add_url_rule("/health/worker", "health_worker", worker, methods=["GET"])
