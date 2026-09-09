from __future__ import annotations

from werkzeug.security import generate_password_hash
from sqlalchemy import func, or_

from ..extensions import db
from ..models import User
from .security import invalidate_user_access, revoke_user_sessions


class AdminOperationError(ValueError):
    pass


def find_user(*, user_id: int | None = None, identifier: str | None = None) -> User:
    user = db.session.get(User, user_id) if user_id is not None else None
    if user is None and identifier:
        normalized = identifier.strip().lower()
        user = User.query.filter(
            or_(func.lower(User.email) == normalized, func.lower(User.eid) == normalized)
        ).first()
    if user is None:
        raise AdminOperationError("User was not found")
    return user


def disable_user(user: User, *, deleted: bool = False) -> None:
    user.active = False
    user.deleted = bool(deleted)
    user.session_epoch += 1
    revoke_user_sessions(user.id)
    invalidate_user_access(user)


def enable_user(user: User) -> None:
    user.active = True
    user.deleted = False
    user.session_epoch += 1
    revoke_user_sessions(user.id)
    invalidate_user_access(user)


def revoke_user_access(user: User) -> None:
    user.session_epoch += 1
    revoke_user_sessions(user.id)
    invalidate_user_access(user)


def revoke_sessions_only(user: User) -> None:
    user.session_epoch += 1
    revoke_user_sessions(user.id)


def set_user_password(user: User, password: str) -> None:
    if len(password) < 12:
        raise AdminOperationError("Password must contain at least 12 characters")
    user.password_hash = generate_password_hash(password)
    user.session_epoch += 1
    revoke_user_sessions(user.id)
