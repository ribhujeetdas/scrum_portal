from __future__ import annotations

from flask import current_app, g, jsonify, render_template, session, flash, redirect, request, url_for
from flask_login import login_required, current_user
from datetime import datetime

from . import main_bp


@main_bp.before_app_request
def enforce_session_timeout():
    """
    Enforce 30-minute idle timeout via session timestamp.
    Flask permanent sessions expire by lifetime; this adds user-friendly message.
    """
    if current_user.is_authenticated:
        now = datetime.utcnow().timestamp()
        last = session.get("last_activity", now)
        session["last_activity"] = now

        # 30 minutes = 1800 seconds
        if (now - last) > 1800:
            from flask_login import logout_user
            logout_user()
            session.clear()
            flash("Session expired (30 minutes). Please login again.", "warning")
            return redirect(url_for("auth.login"))


@main_bp.route("/home", methods=["GET"])
@login_required
def home():
    return render_template("main/home.html")


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
