from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import time

from flask import current_app, jsonify, request
from flask_login import current_user
from sqlalchemy import text

from ..extensions import db
LIMITS = {
    "login": (10, 900),
    "signup": (10, 900),
    "pat_validation": (10, 900),
    "sprint_import": (10, 60),
    "sprint_retry": (5, 60),
    "sprint_poll": (120, 60),
    "rule_create": (5, 60),
    "client_log": (30, 60),
}


def _operation() -> str | None:
    endpoint = request.endpoint or ""
    path = request.path
    if request.method == "POST" and endpoint in {"auth.login", "aliases.auth_login"}: return "login"
    if request.method == "POST" and endpoint in {"auth.signup", "aliases.auth_signup"}: return "signup"
    if request.method == "POST" and endpoint in {"config.integrations", "aliases.settings_integrations"}: return "pat_validation"
    if request.method == "POST" and path.endswith("/retry"): return "sprint_retry"
    if request.method == "GET" and path.endswith("/status") and "sprint-viewer" in path: return "sprint_poll"
    if request.method == "POST" and "rule-copier" in path and path.endswith(("/copy", "/copy-rule")): return "rule_create"
    if request.method == "POST" and path.endswith(("/client-log", "/client_log")): return "client_log"
    return None


def _hash_subject(raw: str) -> str:
    key = str(current_app.config.get("RATE_LIMIT_KEY") or current_app.config["SECRET_KEY"]).encode()
    return hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()


def _subjects(operation: str, default_limit: int) -> list[tuple[str, int]]:
    if operation == "login":
        identifier = str(request.form.get("identifier") or "").strip().casefold()
        address = request.remote_addr or "-"
        return [
            (_hash_subject(f"login-id:{identifier}"), default_limit),
            (_hash_subject(f"login-ip:{address}"), 30),
        ]
    if current_user.is_authenticated:
        return [(_hash_subject(f"user:{current_user.id}"), default_limit)]
    return [(_hash_subject(f"ip:{request.remote_addr or '-'}"), default_limit)]


def _increment(operation: str, subject: str, window_start: int, expires_at: datetime) -> int:
    # SQLite UPSERT makes the increment atomic across web processes.
    value = db.session.execute(
        text(
            "INSERT INTO rate_limit_buckets "
            "(operation, subject_key, window_start, count, expires_at) "
            "VALUES (:operation, :subject, :window_start, 1, :expires_at) "
            "ON CONFLICT(operation, subject_key, window_start) "
            "DO UPDATE SET count = rate_limit_buckets.count + 1 "
            "RETURNING count"
        ),
        {
            "operation": operation,
            "subject": subject,
            "window_start": window_start,
            "expires_at": expires_at,
        },
    ).scalar_one()
    return int(value)


def enforce_rate_limit():
    if not current_app.config.get("RATE_LIMITS_ENABLED", not current_app.config.get("TESTING", False)):
        return None
    operation = _operation()
    if operation is None:
        return None
    limit, seconds = LIMITS[operation]
    now_seconds = int(time.time())
    window_start = now_seconds - (now_seconds % seconds)
    expires_at = datetime.fromtimestamp(window_start, UTC) + timedelta(seconds=seconds * 2)
    exceeded = any(
        _increment(operation, subject, window_start, expires_at) > subject_limit
        for subject, subject_limit in _subjects(operation, limit)
    )
    if exceeded:
        db.session.rollback()
        retry_after = window_start + seconds - now_seconds
        response = jsonify({"ok": False, "error": {"code": "RATE_LIMITED", "message": "Too many requests. Try again shortly.", "retryable": True}})
        response.status_code = 429
        response.headers["Retry-After"] = str(max(1, retry_after))
        return response
    if now_seconds % 127 == 0:
        db.session.execute(
            text("DELETE FROM rate_limit_buckets WHERE expires_at < :now"),
            {"now": datetime.now(UTC)},
        )
    db.session.commit()
    return None


def consume_current_user_limit(operation: str):
    """Consume a logical limit inside the caller's transaction.

    Used when only newly-created work counts; a deduplicated DB hit consumes no
    import admission quota.
    """
    if not current_app.config.get("RATE_LIMITS_ENABLED", not current_app.config.get("TESTING", False)):
        return None
    limit, seconds = LIMITS[operation]
    now_seconds = int(time.time())
    window_start = now_seconds - (now_seconds % seconds)
    expires_at = datetime.fromtimestamp(window_start, UTC) + timedelta(seconds=seconds * 2)
    exceeded = any(
        _increment(operation, subject, window_start, expires_at) > subject_limit
        for subject, subject_limit in _subjects(operation, limit)
    )
    if not exceeded:
        return None
    db.session.rollback()
    response = jsonify({
        "ok": False,
        "error": {
            "code": "RATE_LIMITED",
            "message": "Too many requests. Try again shortly.",
            "retryable": True,
        },
    })
    response.status_code = 429
    response.headers["Retry-After"] = str(max(1, window_start + seconds - now_seconds))
    return response
