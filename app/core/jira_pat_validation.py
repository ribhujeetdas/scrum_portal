from __future__ import annotations

import hashlib
import time
from collections.abc import Callable

from flask import current_app, session
from flask_login import current_user


def validate_jira_pat_for_current_user(
    pat: str,
    fetch_myself: Callable[[str], dict],
) -> None:
    cache_seconds = int(current_app.config.get("JIRA_PAT_VALIDATION_CACHE_SECONDS", 300))
    pat_hash = hashlib.sha256(pat.encode("utf-8")).hexdigest()
    user_id = int(current_user.id)
    email = str(current_user.email or "").strip().lower()

    cache = session.get("jira_pat_validation") or {}
    now = int(time.time())
    if (
        cache_seconds > 0
        and cache.get("user_id") == user_id
        and cache.get("email") == email
        and cache.get("pat_hash") == pat_hash
        and int(cache.get("expires_at") or 0) > now
    ):
        return

    myself = fetch_myself(pat)
    api_email = (myself.get("emailAddress") or "").strip()
    active = bool(myself.get("active"))
    deleted = bool(myself.get("deleted"))
    if api_email.lower() != email:
        raise ValueError("Saved PAT belongs to a different user (email mismatch).")
    if not active or deleted:
        raise ValueError("Jira profile is not active or is deleted.")

    if cache_seconds > 0:
        session["jira_pat_validation"] = {
            "user_id": user_id,
            "email": email,
            "pat_hash": pat_hash,
            "expires_at": now + cache_seconds,
        }
        session.modified = True
