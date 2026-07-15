from __future__ import annotations

import os
import re
import shutil
import time
from urllib.parse import urlsplit, urlunsplit

from flask import (
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, logout_user

from ...core.database import migration_status, sqlite_health
from ...core.rate_limit import enforce_limit
from . import main_bp

_ALLOWED_CLIENT_EVENTS = {
    "fetch.http_error",
    "fetch.network_error",
    "session.status_error",
    "session.extend_error",
    "window.error",
    "window.unhandledrejection",
}
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


@main_bp.before_app_request
def enforce_session_timeout():
    """
    Enforce a configurable absolute session timeout.
    The session is only extended by the explicit /session/extend action.
    """
    if request.endpoint in {"main.health_live", "main.health_ready"}:
        return None
    if not current_user.is_authenticated:
        return None

    timeout_seconds = _session_timeout_seconds()
    now = _now()
    expires_at = session.get("session_expires_at")
    absolute_expires_at = session.get("session_absolute_expires_at")

    if expires_at is None:
        _initialize_session_window(now, timeout_seconds)
        return None

    try:
        expires_at = float(expires_at)
    except (TypeError, ValueError):
        _initialize_session_window(now, timeout_seconds)
        return None

    try:
        absolute_expires_at = float(absolute_expires_at)
    except (TypeError, ValueError):
        absolute_expires_at = now + _absolute_session_seconds()
        session["session_absolute_expires_at"] = int(absolute_expires_at)

    if now <= expires_at and now <= absolute_expires_at:
        return None

    logout_user()
    session.clear()
    if (
        request.path.startswith("/api/")
        or request.endpoint
        in {
            "main.session_status",
            "main.extend_session",
        }
        or request.is_json
    ):
        return jsonify(
            {
                "authenticated": False,
                "expired": True,
                "redirect_url": url_for("aliases.auth_login"),
            }
        ), 401

    flash("Session expired. Please login again.", "warning")
    return redirect(url_for("aliases.auth_login"))


def _now() -> int:
    return int(time.time())


def _session_timeout_seconds() -> int:
    minutes = int(current_app.config.get("SESSION_TIMEOUT_MINUTES", 15))
    return max(60, minutes * 60)


def _warning_ratio() -> float:
    ratio = float(current_app.config.get("SESSION_WARNING_THRESHOLD_RATIO", 0.8))
    return min(max(ratio, 0.1), 0.95)


def _absolute_session_seconds() -> int:
    minutes = int(current_app.config.get("SESSION_ABSOLUTE_MAX_MINUTES", 480))
    return max(_session_timeout_seconds(), minutes * 60)


@main_bp.route("/health/live", methods=["GET"])
def health_live():
    return jsonify(
        {
            "ok": True,
            "status": "live",
            "version": current_app.config.get("APPLICATION_VERSION", "dev"),
        }
    )


@main_bp.route("/health/ready", methods=["GET"])
def health_ready():
    checks: dict[str, object] = {}
    try:
        database = sqlite_health()
        checks["database"] = "ok"
        checks["foreign_keys"] = bool(database["foreign_keys"])
        checks["journal_mode"] = database["journal_mode"]
        migrations = migration_status()
        checks["migrations"] = "current" if migrations["current"] else "pending"

        log_dir = str(current_app.config.get("LOG_DIR", "logs"))
        if not os.path.isabs(log_dir):
            log_dir = os.path.abspath(os.path.join(current_app.root_path, "..", log_dir))
        disk = shutil.disk_usage(log_dir)
        free_mb = int(disk.free / (1024 * 1024))
        checks["log_storage"] = "ok" if os.access(log_dir, os.W_OK) else "unwritable"
        checks["free_disk_mb"] = free_mb
        ready = (
            bool(database["foreign_keys"])
            and bool(migrations["current"])
            and checks["log_storage"] == "ok"
            and free_mb >= int(current_app.config.get("MIN_FREE_DISK_MB", 256))
        )
    except Exception as exc:
        current_app.logger.warning(
            "Readiness check failed",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={"event": "health.ready.failed"},
        )
        checks = {"database": "unavailable"}
        ready = False

    return jsonify(
        {
            "ok": ready,
            "status": "ready" if ready else "not_ready",
            "checks": checks,
            "version": current_app.config.get("APPLICATION_VERSION", "dev"),
        }
    ), (200 if ready else 503)


def _initialize_session_window(now: int, timeout_seconds: int) -> int:
    expires_at = now + timeout_seconds
    session["session_started_at"] = now
    session["session_expires_at"] = expires_at
    session["session_absolute_expires_at"] = now + _absolute_session_seconds()
    session.permanent = True
    return expires_at


def _session_payload(now: int, expires_at: int, timeout_seconds: int) -> dict:
    warning_after_seconds = int(timeout_seconds * _warning_ratio())
    warning_remaining_seconds = max(1, timeout_seconds - warning_after_seconds)
    remaining_seconds = max(0, int(expires_at - now))
    return {
        "authenticated": True,
        "expired": remaining_seconds <= 0,
        "expires_at": int(expires_at),
        "absolute_expires_at": int(session.get("session_absolute_expires_at") or expires_at),
        "remaining_seconds": remaining_seconds,
        "timeout_seconds": timeout_seconds,
        "warning_after_seconds": warning_after_seconds,
        "warning_remaining_seconds": warning_remaining_seconds,
        "show_warning": remaining_seconds <= warning_remaining_seconds,
        "redirect_url": url_for("aliases.auth_login"),
    }


@main_bp.route("/home", methods=["GET"])
@login_required
def home():
    return render_template("main/home.html")


@main_bp.route("/session/status", methods=["GET"])
@login_required
def session_status():
    timeout_seconds = _session_timeout_seconds()
    now = _now()
    expires_at = session.get("session_expires_at")
    if expires_at is None:
        expires_at = _initialize_session_window(now, timeout_seconds)
    return jsonify(_session_payload(now, int(float(expires_at)), timeout_seconds))


@main_bp.route("/session/extend", methods=["POST"])
@login_required
def extend_session():
    timeout_seconds = _session_timeout_seconds()
    now = _now()
    existing_expires_at = session.get("session_expires_at")
    try:
        base_expires_at = max(int(float(existing_expires_at)), now)
    except (TypeError, ValueError):
        base_expires_at = now

    try:
        session_started_at = int(float(session.get("session_started_at", now)))
    except (TypeError, ValueError):
        session_started_at = now
    try:
        absolute_expires_at = int(float(session.get("session_absolute_expires_at")))
    except (TypeError, ValueError):
        absolute_expires_at = session_started_at + _absolute_session_seconds()
        session["session_absolute_expires_at"] = absolute_expires_at
    new_expires_at = min(base_expires_at + timeout_seconds, absolute_expires_at)
    session["session_expires_at"] = new_expires_at
    session.permanent = True

    payload = _session_payload(now, new_expires_at, timeout_seconds)
    payload["ok"] = True
    return jsonify(payload)


@main_bp.route("/client-log", methods=["POST"])
@login_required
def client_log():
    enforce_limit("client.log", subject=str(current_user.id), expensive=True)
    if request.content_length and request.content_length > 8192:
        return jsonify({"ok": False, "error": "Payload too large."}), 413

    payload = request.get_json(silent=True) or {}

    def clean(value, max_len):
        if value is None:
            return ""
        return _CONTROL_CHARACTERS.sub(" ", str(value))[:max_len]

    event = clean(payload.get("event"), 80)
    if event not in _ALLOWED_CLIENT_EVENTS:
        return jsonify({"ok": False, "error": "Unsupported client event."}), 400

    raw_url = clean(payload.get("url"), 500)
    parsed_url = urlsplit(raw_url)
    safe_url = urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", ""))

    current_app.logger.info(
        "client event",
        extra={
            "event": "client.event",
            "client_event": event,
            "client_message": clean(payload.get("message"), 500),
            "client_url": safe_url,
            "client_user_agent": clean(payload.get("userAgent"), 300),
        },
    )
    return jsonify({"ok": True, "request_id": getattr(g, "request_id", "-")})
