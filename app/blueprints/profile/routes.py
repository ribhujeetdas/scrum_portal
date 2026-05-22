# app/blueprints/profile/routes.py
from __future__ import annotations

from flask import render_template
from flask_login import login_required

from . import profile_bp


@profile_bp.route("/", methods=["GET"])
@login_required
def profile():
    # Profile = user details only
    return render_template("profile/profile.html")
