# app/blueprints/auth/routes.py
from __future__ import annotations

import time

from flask import current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf.csrf import CSRFError
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from ...core.api import safe_error_message
from ...core.database import execute_write
from ...core.dependencies import crypto_service, jira_service
from ...core.error_logging import log_handled_exception
from ...core.rate_limit import enforce_limit, reset_limit, subject_hash
from ...extensions import db
from ...logging_conf import audit_event
from ...models import User
from ...services.jira_service import JiraServiceError
from . import auth_bp
from .forms import ConfirmProfileForm, LoginForm, SetPasswordForm, SignupForm

_DUMMY_PASSWORD_HASH = generate_password_hash("portal-dummy-password-value")


def _clear_signup_state() -> None:
    for key in ("signup_email", "signup_profile", "signup_pat_enc", "signup_started_at"):
        session.pop(key, None)


def _signup_state_is_current() -> bool:
    try:
        started_at = int(session.get("signup_started_at") or 0)
    except (TypeError, ValueError):
        return False
    ttl_seconds = int(current_app.config.get("SIGNUP_STATE_TTL_MINUTES", 20)) * 60
    return started_at > 0 and int(time.time()) - started_at <= ttl_seconds


def _login_with_form(form):
    identifier = form.identifier.data.strip()
    password = form.password.data
    limiter_key = enforce_limit("auth.login", subject=identifier)

    user = User.query.filter(or_(User.email.ilike(identifier), User.eid.ilike(identifier))).first()

    password_valid = (
        user.check_password(password)
        if user
        else check_password_hash(_DUMMY_PASSWORD_HASH, password)
    )
    if not user or not password_valid:
        current_app.logger.warning(
            "Failed login attempt",
            extra={
                "event": "auth.login.failed",
                "identifier_hash": subject_hash(identifier),
                "result": "invalid_credentials",
            },
        )
        audit_event(
            "auth.login.failed",
            "Login rejected",
            identifier_hash=subject_hash(identifier),
            result="invalid_credentials",
        )
        flash("Invalid credentials.", "danger")
        return render_template("auth/login.html", form=form)

    if not user.active or user.deleted:
        audit_event(
            "auth.login.failed",
            "Login rejected",
            identifier_hash=subject_hash(identifier),
            result="inactive_account",
        )
        flash("Your account is inactive. Contact admin.", "danger")
        return render_template("auth/login.html", form=form)

    session.clear()
    login_user(user)
    session.permanent = True
    now = int(time.time())
    timeout_seconds = int(current_app.config.get("SESSION_TIMEOUT_MINUTES", 15)) * 60
    absolute_seconds = max(
        timeout_seconds,
        int(current_app.config.get("SESSION_ABSOLUTE_MAX_MINUTES", 480)) * 60,
    )
    session["session_started_at"] = now
    session["session_expires_at"] = now + timeout_seconds
    session["session_absolute_expires_at"] = now + absolute_seconds
    reset_limit("auth.login", limiter_key)
    current_app.logger.info(
        "User logged in",
        extra={"event": "auth.login.succeeded", "result": "success"},
    )
    audit_event("auth.login.succeeded", "User login succeeded", result="success")
    return redirect(url_for("aliases.dashboard"))


@auth_bp.app_errorhandler(CSRFError)
def handle_auth_csrf_error(error):
    if request.endpoint in {"auth.login", "aliases.auth_login"} and request.method == "POST":
        flash("Session expired. Please login again.", "warning")
        current_app.logger.warning(
            "Login CSRF validation failed",
            extra={"event": "auth.login.csrf_failed", "result": "rejected"},
        )
        audit_event("auth.login.csrf_failed", "Login CSRF rejected", result="rejected")
        return render_template("auth/login.html", form=LoginForm()), 400

    current_app.logger.warning("CSRF validation failed: %s", error.description)
    return render_template("error.html", code=400, message="CSRF validation failed."), 400


@auth_bp.route("/", methods=["GET"])
def root():
    return redirect(url_for("aliases.auth_login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # If already logged in, go to home (so sidebar/logout is present)
    if current_user.is_authenticated:
        return redirect(url_for("aliases.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        return _login_with_form(form)

    if request.args.get("next"):
        flash("Please login to continue.", "warning")

    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    audit_event("auth.logout", "User logged out", result="success")
    logout_user()
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for("aliases.auth_login"))


@auth_bp.route("/forgot-password", methods=["GET"])
def forgot_password():
    admin_email = current_app.config["ADMIN_EMAIL"]
    flash(f"Password reset is managed by Admin. Please contact: {admin_email}", "warning")
    return redirect(url_for("aliases.auth_login"))


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    # If already logged in, go to home
    if current_user.is_authenticated:
        return redirect(url_for("aliases.dashboard"))

    form = SignupForm()
    if form.validate_on_submit():
        email = form.email.data.strip()
        pat = form.jira_pat.data.strip()
        enforce_limit("auth.signup", subject=email)

        existing = User.query.filter(User.email.ilike(email)).first()
        if existing:
            audit_event(
                "auth.signup.failed",
                "Signup rejected",
                identifier_hash=subject_hash(email),
                result="account_exists",
            )
            flash("Account already exists for this email. Please login.", "info")
            return redirect(url_for("aliases.auth_login"))

        try:
            profile = jira_service().fetch_myself(pat)
        except JiraServiceError as exc:
            log_handled_exception(
                "Signup PAT validation failed",
                exc,
                event="auth.signup.pat_validation_failed",
                feature="auth",
                operation="signup",
                context={"identifier_hash": subject_hash(email)},
            )
            audit_event(
                "auth.signup.failed",
                "Signup rejected",
                identifier_hash=subject_hash(email),
                result="pat_validation_failed",
            )
            flash(safe_error_message("validate Jira profile"), "danger")
            return render_template("auth/signup.html", form=form)

        api_email = (profile.get("emailAddress") or "").strip()
        active = bool(profile.get("active"))
        deleted = bool(profile.get("deleted"))

        if not active or deleted:
            audit_event(
                "auth.signup.failed",
                "Signup rejected",
                identifier_hash=subject_hash(email),
                result="inactive_identity",
            )
            flash("Jira profile is not active or is deleted.", "danger")
            return render_template("auth/signup.html", form=form)

        if api_email.lower() != email.lower():
            audit_event(
                "auth.signup.failed",
                "Signup rejected",
                identifier_hash=subject_hash(email),
                result="identity_mismatch",
            )
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
        session["signup_started_at"] = int(time.time())

        current_app.logger.info(
            "Signup identity validated",
            extra={"event": "auth.signup.identity_validated", "result": "success"},
        )
        return redirect(url_for("aliases.auth_signup_confirm"))

    return render_template("auth/signup.html", form=form)


@auth_bp.route("/signup/confirm", methods=["GET", "POST"])
def confirm_profile():
    profile = session.get("signup_profile")
    if not profile or not _signup_state_is_current():
        _clear_signup_state()
        flash("Signup session expired. Please start again.", "warning")
        return redirect(url_for("aliases.auth_signup"))

    form = ConfirmProfileForm()
    if form.validate_on_submit():
        return redirect(url_for("aliases.auth_signup_set_password"))

    return render_template("auth/confirm_profile.html", profile=profile, form=form)


@auth_bp.route("/signup/set-password", methods=["GET", "POST"])
def set_password():
    profile = session.get("signup_profile")
    pat_enc_str = session.get("signup_pat_enc")

    if not profile or not pat_enc_str or not _signup_state_is_current():
        _clear_signup_state()
        flash("Signup session expired. Please start again.", "warning")
        return redirect(url_for("aliases.auth_signup"))

    form = SetPasswordForm()
    if form.validate_on_submit():
        eid = (profile.get("eid") or "").strip()
        email = (profile.get("email") or "").strip()
        display_name = (profile.get("display_name") or "").strip()

        if not eid or not email or not display_name:
            flash("Invalid profile data. Please retry signup.", "danger")
            return redirect(url_for("aliases.auth_signup"))

        if (
            User.query.filter(User.email.ilike(email)).first()
            or User.query.filter(User.eid.ilike(eid)).first()
        ):
            flash("Account already exists. Please login.", "info")
            return redirect(url_for("aliases.auth_login"))

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

        try:
            execute_write(lambda: db.session.add(user))
        except IntegrityError:
            flash("Account already exists. Please login.", "info")
            return redirect(url_for("aliases.auth_login"))

        _clear_signup_state()

        current_app.logger.info(
            "User account created",
            extra={"event": "auth.signup.succeeded", "result": "success"},
        )
        audit_event(
            "auth.signup.succeeded",
            "User account created",
            resource_type="user",
            resource_id=str(user.id),
            result="success",
        )
        flash("Account created successfully. Please login.", "success")
        return redirect(url_for("aliases.auth_login"))

    return render_template("auth/set_password.html", form=form)
