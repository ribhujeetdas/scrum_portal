from __future__ import annotations

import time

from flask import current_app, g, jsonify, render_template, session, flash, redirect, request, url_for
from flask_login import login_required, current_user, logout_user

from . import main_bp


@main_bp.before_app_request
def enforce_session_timeout():
    """
    Enforce a configurable absolute session timeout.
    The session is only extended by the explicit /session/extend action.
    """
    if not current_user.is_authenticated:
        return None

    timeout_seconds = _session_timeout_seconds()
    now = _now()
    expires_at = session.get("session_expires_at")

    if not expires_at:
        _initialize_session_window(now, timeout_seconds)
        return None

    try:
        expires_at = float(expires_at)
    except (TypeError, ValueError):
        _initialize_session_window(now, timeout_seconds)
        return None

    if now <= expires_at:
        return None

    logout_user()
    session.clear()
    if request.endpoint in {"main.session_status", "main.extend_session"} or request.is_json:
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


def _initialize_session_window(now: int, timeout_seconds: int) -> int:
    expires_at = now + timeout_seconds
    session["session_started_at"] = now
    session["session_expires_at"] = expires_at
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
    if not expires_at:
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

    new_expires_at = base_expires_at + timeout_seconds
    session["session_expires_at"] = new_expires_at
    session.permanent = True

    payload = _session_payload(now, new_expires_at, timeout_seconds)
    payload["ok"] = True
    return jsonify(payload)


@main_bp.route("/client-log", methods=["POST"])
def client_log():
    if request.content_length and request.content_length > 8192:
        return jsonify({"ok": False, "error": "Payload too large."}), 413

    payload = request.get_json(silent=True) or {}

    def clean(value, max_len):
        if value is None:
            return ""
        return str(value).replace("\x00", "")[:max_len]

    current_app.logger.info(
        "client event",
        extra={
            "event": "client.event",
            "client_event": clean(payload.get("event"), 80),
            "client_message": clean(payload.get("message"), 500),
            "client_url": clean(payload.get("url"), 500),
            "client_user_agent": clean(payload.get("userAgent"), 300),
        },
    )
    return jsonify({"ok": True, "request_id": getattr(g, "request_id", "-")})
