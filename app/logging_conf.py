from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Optional

from flask import Flask, g, has_request_context, request

try:
    from concurrent_log_handler import ConcurrentTimedRotatingFileHandler
except Exception:  # pragma: no cover
    ConcurrentTimedRotatingFileHandler = None  # type: ignore

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

_SAFE_REQUEST_ID_RE = re.compile(r"[^A-Za-z0-9_.:-]")
_SECRET_PATTERNS = (
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE), r"\1<redacted>"),
    (re.compile(r"(\bpat[_ -]?(?:secret|token)?\b\s*[=:]\s*)\S+", re.IGNORECASE), r"\1<redacted>"),
    (re.compile(r"(\bpassword\b\s*[=:]\s*)\S+", re.IGNORECASE), r"\1<redacted>"),
    (re.compile(r"(\bcsrf[_ -]?token\b\s*[=:]\s*)\S+", re.IGNORECASE), r"\1<redacted>"),
)
_SECRET_KEY_FRAGMENTS = (
    "authorization",
    "csrf",
    "password",
    "pat",
    "secret",
    "token",
)


def set_request_id(value: str) -> None:
    _request_id_ctx.set(value or "-")


def get_request_id() -> str:
    return _request_id_ctx.get()


def _redact(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        redacted = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(fragment in key_text for fragment in _SECRET_KEY_FRAGMENTS):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_redact(item) for item in value]
    if not isinstance(value, str):
        return value
    out = value
    for pattern, replacement in _SECRET_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def _clean_request_id(value: str | None) -> str:
    if not value:
        return uuid.uuid4().hex
    cleaned = _SAFE_REQUEST_ID_RE.sub("", value.strip())
    return cleaned[:64] or uuid.uuid4().hex


class RequestContextFilter(logging.Filter):
    """Adds request/user correlation fields to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id() or "-"
        if not hasattr(record, "method"):
            record.method = None
        if not hasattr(record, "path"):
            record.path = None
        if not hasattr(record, "endpoint"):
            record.endpoint = None
        if not hasattr(record, "status_code"):
            record.status_code = None
        if not hasattr(record, "duration_ms"):
            record.duration_ms = None
        if not hasattr(record, "user_id"):
            record.user_id = None
        if not hasattr(record, "eid"):
            record.eid = None

        if has_request_context():
            record.request_id = getattr(g, "request_id", None) or record.request_id
            record.method = request.method
            record.path = request.path
            record.endpoint = request.endpoint

            try:
                from flask_login import current_user

                if current_user.is_authenticated:
                    record.user_id = getattr(current_user, "id", None)
                    record.eid = getattr(current_user, "eid", None)
            except Exception:
                pass
        return True


class JsonFormatter(logging.Formatter):
    def __init__(self, tz_name: str):
        super().__init__()
        self._tz_name = tz_name

    def formatTime(self, record: logging.LogRecord, datefmt: Optional[str] = None) -> str:
        tz = None
        if ZoneInfo is not None:
            try:
                tz = ZoneInfo(self._tz_name)
            except Exception:
                tz = None
        dt = datetime.fromtimestamp(record.created, tz=tz)
        return dt.isoformat(timespec="milliseconds")

    def format(self, record: logging.LogRecord) -> str:
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
        else:
            exc_text = None

        payload: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact(record.getMessage()),
            "event": getattr(record, "event", None),
            "request_id": getattr(record, "request_id", "-"),
            "method": getattr(record, "method", None),
            "path": getattr(record, "path", None),
            "endpoint": getattr(record, "endpoint", None),
            "status_code": getattr(record, "status_code", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "user_id": getattr(record, "user_id", None),
            "eid": getattr(record, "eid", None),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }

        for key in (
            "client_event",
            "client_message",
            "client_url",
            "client_user_agent",
            "context",
            "error_type",
            "external_operation",
            "external_endpoint",
            "external_response_snippet",
            "external_service",
            "external_status_code",
            "feature",
            "operation",
            "remote_addr",
        ):
            if hasattr(record, key):
                payload[key] = _redact(getattr(record, key))

        if exc_text:
            payload["exception"] = _redact(exc_text)

        return json.dumps(
            {k: v for k, v in payload.items() if v is not None},
            ensure_ascii=True,
            default=str,
        )


class TextFormatter(logging.Formatter):
    def __init__(self, tz_name: str):
        fmt = (
            "%(asctime)s %(levelname)s %(name)s "
            "[req=%(request_id)s user=%(user_id)s] %(message)s"
        )
        super().__init__(fmt=fmt, datefmt="%Y-%m-%d %H:%M:%S")
        self._tz_name = tz_name

    def formatTime(self, record: logging.LogRecord, datefmt: Optional[str] = None) -> str:
        tz = None
        if ZoneInfo is not None:
            try:
                tz = ZoneInfo(self._tz_name)
            except Exception:
                tz = None
        dt = datetime.fromtimestamp(record.created, tz=tz)
        return dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        return str(_redact(rendered))


def _config_bool(app: Flask, primary: str, legacy: str, default: bool) -> bool:
    value = app.config.get(primary, app.config.get(legacy, default))
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _config_value(app: Flask, primary: str, legacy: str, default: Any) -> Any:
    return app.config.get(primary, app.config.get(legacy, default))


def _absolute_log_dir(app: Flask, configured: str) -> str:
    if os.path.isabs(configured):
        return configured
    return os.path.abspath(os.path.join(app.root_path, "..", configured))


def _build_file_handler(logfile: str, backups: int) -> logging.Handler:
    if ConcurrentTimedRotatingFileHandler is not None:
        return ConcurrentTimedRotatingFileHandler(
            logfile,
            when="midnight",
            interval=1,
            backupCount=backups,
            encoding="utf-8",
            utc=False,
        )

    from logging.handlers import TimedRotatingFileHandler

    return TimedRotatingFileHandler(
        logfile,
        when="midnight",
        interval=1,
        backupCount=backups,
        encoding="utf-8",
        utc=False,
    )


def _remove_owned_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if getattr(handler, "_scrum_portal_handler", False):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass


def init_request_correlation(app: Flask) -> None:
    @app.before_request
    def _before_request_set_request_id():
        rid = _clean_request_id(request.headers.get("X-Request-ID"))
        g.request_id = rid
        g.request_started_at = time.perf_counter()
        set_request_id(rid)

    @app.after_request
    def _after_request_log_response(response):
        rid = getattr(g, "request_id", None) or get_request_id()
        response.headers["X-Request-ID"] = rid

        started = getattr(g, "request_started_at", None)
        duration_ms = None
        if started is not None:
            duration_ms = int((time.perf_counter() - started) * 1000)

        logging.getLogger("app.request").info(
            "request complete",
            extra={
                "event": "request.complete",
                "request_id": rid,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "remote_addr": request.headers.get("X-Forwarded-For", request.remote_addr),
            },
        )
        return response

    @app.teardown_request
    def _teardown_request_log_exception(exc):
        if exc is None:
            return
        started = getattr(g, "request_started_at", None)
        duration_ms = None
        if started is not None:
            duration_ms = int((time.perf_counter() - started) * 1000)
        logging.getLogger("app.request").error(
            "request exception",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={
                "event": "request.exception",
                "request_id": getattr(g, "request_id", None) or get_request_id(),
                "duration_ms": duration_ms,
            },
        )


def configure_logging(app: Flask) -> None:
    log_level = str(app.config.get("LOG_LEVEL", "INFO")).upper()
    tz_name = str(_config_value(app, "LOG_TIMEZONE", "LOG_TZ", "Asia/Kolkata"))
    log_format = str(app.config.get("LOG_FORMAT", "json")).lower()
    enable_console = _config_bool(app, "LOG_TO_CONSOLE", "LOG_CONSOLE", False)
    backups = int(_config_value(app, "LOG_BACKUPS", "LOG_BACKUP_DAYS", 14))
    log_file = str(_config_value(app, "LOG_FILE", "LOG_FILE_NAME", "app.log"))

    logs_dir = _absolute_log_dir(app, str(app.config.get("LOG_DIR", "logs")))
    os.makedirs(logs_dir, exist_ok=True)
    logfile = os.path.join(logs_dir, log_file)

    level_num = logging.getLevelName(log_level)
    if isinstance(level_num, str):
        level_num = logging.INFO

    formatter: logging.Formatter
    if log_format == "text":
        formatter = TextFormatter(tz_name=tz_name)
    else:
        formatter = JsonFormatter(tz_name=tz_name)

    context_filter = RequestContextFilter()
    root_logger = logging.getLogger()
    _remove_owned_handlers(root_logger)

    app_logger = logging.getLogger("app")
    for handler in list(app_logger.handlers):
        app_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    app_logger.setLevel(level_num)
    app_logger.propagate = False

    file_handler = _build_file_handler(logfile, backups)
    file_handler._scrum_portal_handler = True  # type: ignore[attr-defined]
    file_handler.setLevel(level_num)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(context_filter)
    app_logger.addHandler(file_handler)

    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler._scrum_portal_handler = True  # type: ignore[attr-defined]
        console_handler.setLevel(level_num)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(context_filter)
        app_logger.addHandler(console_handler)

    for handler in list(app.logger.handlers):
        if handler not in app_logger.handlers:
            app.logger.removeHandler(handler)
    app.logger.propagate = False
    app.logger.setLevel(level_num)

    logging.getLogger("werkzeug").setLevel(
        app.config.get("LOG_WERKZEUG_LEVEL", app.config.get("WERKZEUG_LOG_LEVEL", "WARNING"))
    )
    logging.getLogger("urllib3").setLevel(
        app.config.get("LOG_URLLIB3_LEVEL", app.config.get("URLLIB3_LOG_LEVEL", "WARNING"))
    )
    logging.getLogger("requests").setLevel(
        app.config.get("REQUESTS_LOG_LEVEL", app.config.get("LOG_URLLIB3_LEVEL", "WARNING"))
    )
    logging.getLogger("sqlalchemy").setLevel(app.config.get("LOG_SQLALCHEMY_LEVEL", "WARNING"))

    logging.getLogger("app").info(
        "logging configured",
        extra={
            "event": "logging.configured",
            "logfile": logfile,
            "log_level": logging.getLevelName(level_num),
        },
    )
