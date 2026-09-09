from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flask import current_app, jsonify, request, session, url_for
from flask_login import current_user, logout_user

from ..extensions import db
from ..models import AuthSession, User


AUTH_SESSION_KEY = "auth_session_id"
AUTH_EPOCH_KEY = "auth_session_epoch"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def start_auth_session(user: User) -> AuthSession:
    now = datetime.now(UTC)
    record = AuthSession(
        user_id=user.id,
        session_epoch=user.session_epoch,
        expires_at=now + timedelta(minutes=int(current_app.config["SESSION_TIMEOUT_MINUTES"])),
    )
    db.session.add(record)
    db.session.flush()
    session[AUTH_SESSION_KEY] = record.id
    session[AUTH_EPOCH_KEY] = user.session_epoch
    return record


def revoke_current_auth_session() -> None:
    record_id = session.get(AUTH_SESSION_KEY)
    if record_id:
        record = db.session.get(AuthSession, str(record_id))
        if record and record.revoked_at is None:
            record.revoked_at = datetime.now(UTC)
            db.session.commit()


def revoke_user_sessions(user_id: int) -> None:
    now = datetime.now(UTC)
    AuthSession.query.filter_by(user_id=user_id, revoked_at=None).update(
        {AuthSession.revoked_at: now}, synchronize_session=False
    )


def invalidate_user_access(user: User, *, credentials_changed: bool = False) -> None:
    user.access_epoch += 1
    if credentials_changed:
        user.jira_credential_epoch += 1
    from ..features.automation.sprint_viewer.models import JiraScope, ReportView, BackgroundJob

    now = datetime.now(UTC)
    scope_ids = [
        value for (value,) in db.session.query(JiraScope.id).filter(
            JiraScope.user_id == user.id, JiraScope.revoked_at.is_(None)
        ).all()
    ]
    if scope_ids:
        JiraScope.query.filter(JiraScope.id.in_(scope_ids)).update(
            {JiraScope.revoked_at: now}, synchronize_session=False
        )
        ReportView.query.filter(ReportView.scope_id.in_(scope_ids), ReportView.revoked_at.is_(None)).update(
            {ReportView.revoked_at: now, ReportView.error_code: "SCOPE_REVOKED"},
            synchronize_session=False,
        )
        BackgroundJob.query.filter(
            BackgroundJob.scope_id.in_(scope_ids),
            BackgroundJob.state.in_(("queued", "running", "retry_wait")),
        ).update(
            {BackgroundJob.state: "cancelled", BackgroundJob.error_code: "SCOPE_REVOKED"},
            synchronize_session=False,
        )


def enforce_server_session():
    if not current_user.is_authenticated:
        return None
    if current_app.config.get("TESTING") and not current_app.config.get("REQUIRE_SERVER_AUTH_SESSION", False):
        return None
    record_id = session.get(AUTH_SESSION_KEY)
    try:
        record = db.session.get(AuthSession, str(record_id)) if record_id else None
    except Exception:
        record = None
    now = datetime.now(UTC)
    valid = bool(
        record
        and record.user_id == current_user.id
        and record.revoked_at is None
        and record.session_epoch == current_user.session_epoch
        and session.get(AUTH_EPOCH_KEY) == current_user.session_epoch
        and _aware(record.expires_at) >= now
        and current_user.is_active
    )
    if valid:
        return None
    logout_user()
    session.clear()
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({
            "ok": False,
            "error": {"code": "AUTH_SESSION_INVALID", "message": "Authentication is required."},
            "redirect_url": url_for("aliases.auth_login"),
        }), 401
    return None
