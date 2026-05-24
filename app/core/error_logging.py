from __future__ import annotations

import logging
from typing import Any

from flask import current_app, has_app_context

from .http_client import ExternalServiceError


def _external_error(exc: BaseException) -> ExternalServiceError | None:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, ExternalServiceError):
            return current
        current = current.__cause__
    return None


def log_handled_exception(
    message: str,
    exc: BaseException,
    *,
    event: str,
    feature: str,
    operation: str,
    level: int = logging.WARNING,
    context: dict[str, Any] | None = None,
    logger: logging.Logger | None = None,
) -> None:
    target_logger = logger
    if target_logger is None:
        target_logger = current_app.logger if has_app_context() else logging.getLogger("app")

    extra: dict[str, Any] = {
        "event": event,
        "feature": feature,
        "operation": operation,
        "error_type": type(exc).__name__,
    }
    if context:
        extra["context"] = context
    external_exc = _external_error(exc)
    if external_exc:
        extra.update(
            {
                "external_service": external_exc.service,
                "external_operation": external_exc.operation,
                "external_endpoint": external_exc.endpoint,
                "external_status_code": external_exc.status_code,
                "external_response_snippet": external_exc.response_snippet,
            }
        )

    target_logger.log(
        level,
        message,
        exc_info=(type(exc), exc, exc.__traceback__),
        extra=extra,
    )
