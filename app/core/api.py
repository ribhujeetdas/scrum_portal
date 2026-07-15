from __future__ import annotations

from typing import Any

from flask import g, jsonify

from .redaction import redact


def _request_id() -> str | None:
    return getattr(g, "request_id", None)


def json_error(
    message: str,
    *,
    status_code: int = 400,
    code: str | None = None,
    details: Any | None = None,
):
    error: dict[str, Any] = {"message": message}
    if code:
        error["code"] = code
    if details is not None:
        error["details"] = redact(details)

    payload: dict[str, Any] = {"ok": False, "error": error}
    rid = _request_id()
    if rid:
        payload["request_id"] = rid
    return jsonify(payload), status_code


def safe_error_message(action: str = "complete the request") -> str:
    return (
        f"Unable to {action}. Please try again. "
        "If it continues, contact support with the request ID."
    )


def json_ok(**payload: Any):
    response: dict[str, Any] = {"ok": True, **payload}
    rid = _request_id()
    if rid:
        response["request_id"] = rid
    return jsonify(response)
