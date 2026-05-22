from __future__ import annotations

from flask import render_template, session, flash, redirect, url_for
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
