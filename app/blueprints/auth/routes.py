# app/blueprints/auth/routes.py
from __future__ import annotations

from flask import current_app, render_template, redirect, url_for, flash, session, request
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import or_

from . import auth_bp
from .forms import LoginForm, SignupForm, ConfirmProfileForm, SetPasswordForm
from ...core.dependencies import crypto_service, jira_service
from ...extensions import db
from ...models import User
from ...services.jira_service import JiraServiceError


@auth_bp.route("/", methods=["GET"])
def root():
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # If already logged in, go to home (so sidebar/logout is present)
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    form = LoginForm()
    if form.validate_on_submit():
        identifier = form.identifier.data.strip()
        password = form.password.data

        user = User.query.filter(or_(User.email.ilike(
            identifier), User.eid.ilike(identifier))).first()

        if not user or not user.check_password(password):
            current_app.logger.warning(
                "Failed login attempt for identifier=%s", identifier)
            flash("Invalid credentials.", "danger")
            return render_template("auth/login.html", form=form)

        if not user.active or user.deleted:
            flash("Your account is inactive. Contact admin.", "danger")
            return render_template("auth/login.html", form=form)

        login_user(user)
        session.permanent = True
        current_app.logger.info("User logged in: eid=%s", user.eid)
        return redirect(url_for("main.home"))

    if request.args.get("next"):
        flash("Please login to continue.", "warning")

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/forgot-password", methods=["GET"])
def forgot_password():
    admin_email = current_app.config["ADMIN_EMAIL"]
    flash(
        f"Password reset is managed by Admin. Please contact: {admin_email}", "warning")
    return redirect(url_for("auth.login"))


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    # If already logged in, go to home
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    form = SignupForm()
    if form.validate_on_submit():
        email = form.email.data.strip()
        pat = form.jira_pat.data.strip()

        existing = User.query.filter(User.email.ilike(email)).first()
        if existing:
            flash("Account already exists for this email. Please login.", "info")
            return redirect(url_for("auth.login"))

        try:
            profile = jira_service().fetch_myself(pat)
        except JiraServiceError as exc:
            current_app.logger.warning(
                "Signup PAT validation failed for email=%s: %s", email, exc)
            flash(str(exc), "danger")
            return render_template("auth/signup.html", form=form)

        api_email = (profile.get("emailAddress") or "").strip()
        active = bool(profile.get("active"))
        deleted = bool(profile.get("deleted"))

        if not active or deleted:
            flash("Jira profile is not active or is deleted.", "danger")
            return render_template("auth/signup.html", form=form)

        if api_email.lower() != email.lower():
            flash("Provided email does not match Jira profile email.", "danger")
            return render_template("auth/signup.html", form=form)

        session["signup_email"] = email
        session["signup_profile"] = {
            "eid": profile.get("name"),
            "jira_key": profile.get("key"),
            "email": api_email,
            "display_name": profile.get("displayName"),
            "active": active,
            "deleted": deleted,
            "timezone": profile.get("timeZone"),
            "locale": profile.get("locale"),
        }
        session["signup_pat_enc"] = crypto_service().encrypt(pat).decode("utf-8")

        current_app.logger.info(
            "Signup validated for email=%s eid=%s", api_email, profile.get("name"))
        return redirect(url_for("auth.confirm_profile"))

    return render_template("auth/signup.html", form=form)


@auth_bp.route("/signup/confirm", methods=["GET", "POST"])
def confirm_profile():
    profile = session.get("signup_profile")
    if not profile:
        flash("Signup session expired. Please start again.", "warning")
        return redirect(url_for("auth.signup"))

    form = ConfirmProfileForm()
    if form.validate_on_submit():
        return redirect(url_for("auth.set_password"))

    return render_template("auth/confirm_profile.html", profile=profile, form=form)


@auth_bp.route("/signup/set-password", methods=["GET", "POST"])
def set_password():
    profile = session.get("signup_profile")
    pat_enc_str = session.get("signup_pat_enc")

    if not profile or not pat_enc_str:
        flash("Signup session expired. Please start again.", "warning")
        return redirect(url_for("auth.signup"))

    form = SetPasswordForm()
    if form.validate_on_submit():
        eid = (profile.get("eid") or "").strip()
        email = (profile.get("email") or "").strip()
        display_name = (profile.get("display_name") or "").strip()

        if not eid or not email or not display_name:
            flash("Invalid profile data. Please retry signup.", "danger")
            return redirect(url_for("auth.signup"))

        if User.query.filter(User.email.ilike(email)).first() or User.query.filter(User.eid.ilike(eid)).first():
            flash("Account already exists. Please login.", "info")
            return redirect(url_for("auth.login"))

        user = User(
            eid=eid,
            jira_key=profile.get("jira_key"),
            email=email,
            display_name=display_name,
            active=bool(profile.get("active")),
            deleted=bool(profile.get("deleted")),
            timezone=profile.get("timezone"),
            locale=profile.get("locale"),
        )
        user.set_password(form.password.data)
        user.jira_pat_enc = pat_enc_str.encode("utf-8")

        db.session.add(user)
        db.session.commit()

        session.pop("signup_profile", None)
        session.pop("signup_pat_enc", None)
        session.pop("signup_email", None)

        current_app.logger.info(
            "User created eid=%s email=%s", user.eid, user.email)
        flash("Account created successfully. Please login.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/set_password.html", form=form)
