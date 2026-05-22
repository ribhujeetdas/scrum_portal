from __future__ import annotations

import contextvars
import logging
import os
import uuid
from datetime import datetime
from logging import Logger
from typing import Optional

from flask import Flask, g, has_request_context, request

try:
    # Windows-safe rotating handler (handles Windows file locks)
    from concurrent_log_handler import ConcurrentTimedRotatingFileHandler
except Exception:  # pragma: no cover
    ConcurrentTimedRotatingFileHandler = None  # type: ignore

try:
    # Python 3.9+
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


# Context var so services can log request_id even deep in call stacks
_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-")


def set_request_id(value: str) -> None:
    _request_id_ctx.set(value)


def get_request_id() -> str:
    return _request_id_ctx.get()


class RequestIdFilter(logging.Filter):
    """
    Injects request_id into log records so formatter never fails.
    Priority:
    1) Flask request context g.request_id
    2) contextvar request_id (useful for nested service calls)
    3) "-"
    """

    def filter(self, record: logging.LogRecord) -> bool:
        rid = "-"
        if has_request_context():
            rid = getattr(g, "request_id", None) or "-"
        else:
            rid = get_request_id() or "-"
        record.request_id = rid
        return True


class TZFormatter(logging.Formatter):
    """
    Formatter that renders timestamps in configured timezone (IST by default).
    """

    def __init__(self, fmt: str, tz_name: str):
        super().__init__(fmt)
        self._tz_name = tz_name

    def formatTime(self, record: logging.LogRecord, datefmt: Optional[str] = None) -> str:
        # Best-effort timezone conversion; fallback to default formatter behavior if ZoneInfo missing
        dt = datetime.fromtimestamp(record.created)
        if ZoneInfo is not None:
            try:
                dt = dt.astimezone(ZoneInfo(self._tz_name))
            except Exception:
                pass
        if datefmt:
            return dt.strftime(datefmt)
        return dt.isoformat(timespec="seconds")


def _handler_already_added(logger: Logger, logfile: str) -> bool:
    """Detect if a file handler for the same logfile is already attached."""
    for h in logger.handlers:
        base = getattr(h, "baseFilename", None)
        if base and os.path.abspath(base) == os.path.abspath(logfile):
            return True
    return False


def _has_stream_handler(logger: Logger) -> bool:
    """Detect if a StreamHandler is already attached (prevents console duplicates)."""
    for h in logger.handlers:
        if isinstance(h, logging.StreamHandler):
            return True
    return False


def init_request_correlation(app: Flask) -> None:
    """
    Adds request correlation:
    - Generates/propagates request id
    - Stores in flask.g and contextvar so all downstream logs include it
    - Accepts incoming X-Request-ID if present (optional)
    """

    @app.before_request
    def _before_request_set_request_id():
        incoming = request.headers.get("X-Request-ID")
        rid = (incoming or uuid.uuid4().hex)[:12]
        g.request_id = rid
        set_request_id(rid)


def configure_logging(app: Flask) -> None:
    """
    Comprehensive, config-driven logging:
    - Single file: app.log
    - Rotation: daily at 00:00 in configured timezone (IST recommended)
    - Request correlation via request_id
    - Optional console logging
    - Noise control for werkzeug/urllib3

    IMPORTANT:
    - This function is idempotent (won't add duplicate handlers)
    - Prevents duplicate logs by disabling propagation
    """
    # -----------------------
    # Config (with defaults)
    # -----------------------
    log_level = app.config.get("LOG_LEVEL", "DEBUG")
    tz_name = app.config.get("LOG_TZ", "Asia/Kolkata")
    enable_console = bool(app.config.get("LOG_CONSOLE", True))

    # logs/ folder under repo root (one level above app/)
    logs_dir = app.config.get("LOG_DIR")
    if not logs_dir:
        logs_dir = os.path.join(app.root_path, "..", "logs")
    os.makedirs(logs_dir, exist_ok=True)

    logfile = os.path.join(logs_dir, app.config.get("LOG_FILE", "app.log"))

    # -----------------------
    # Prevent duplicates
    # -----------------------
    # Remove any default handlers that Flask/dev server might attach.
    # (If we don't do this, messages often get printed twice.)
    for h in list(app.logger.handlers):
        app.logger.removeHandler(h)

    # Stop app logger records from also bubbling to root (another common duplication cause)
    app.logger.propagate = False

    # Set level
    level_num = logging.getLevelName(log_level)
    if isinstance(level_num, str):
        # If invalid string, default to DEBUG
        level_num = logging.DEBUG
    app.logger.setLevel(level_num)

    # -----------------------
    # Formatters + filters
    # -----------------------
    # Include request_id always
    fmt = "%(asctime)s %(levelname)s %(name)s [req=%(request_id)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    formatter = TZFormatter(fmt=fmt, tz_name=tz_name)
    formatter.default_time_format = datefmt  # for compatibility
    formatter.default_msec_format = "%s.%03d"

    rid_filter = RequestIdFilter()

    # -----------------------
    # File handler (rotating)
    # -----------------------
    file_handler: Optional[logging.Handler] = None
    if ConcurrentTimedRotatingFileHandler is not None:
        file_handler = ConcurrentTimedRotatingFileHandler(
            logfile,
            when="midnight",
            interval=1,
            backupCount=int(app.config.get("LOG_BACKUPS", 14)),
            encoding="utf-8",
            utc=False,  # local midnight (timezone handled in formatter)
        )
    else:
        # Fallback: standard TimedRotatingFileHandler
        from logging.handlers import TimedRotatingFileHandler

        file_handler = TimedRotatingFileHandler(
            logfile,
            when="midnight",
            interval=1,
            backupCount=int(app.config.get("LOG_BACKUPS", 14)),
            encoding="utf-8",
            utc=False,
        )

    file_handler.setLevel(level_num)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(rid_filter)

    if not _handler_already_added(app.logger, logfile):
        app.logger.addHandler(file_handler)

    # -----------------------
    # Console handler (optional)
    # -----------------------
    if enable_console and not _has_stream_handler(app.logger):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level_num)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(rid_filter)
        app.logger.addHandler(console_handler)

    # -----------------------
    # Noise control (optional)
    # -----------------------
    logging.getLogger("werkzeug").setLevel(
        app.config.get("WERKZEUG_LOG_LEVEL", "WARNING"))
    logging.getLogger("urllib3").setLevel(
        app.config.get("URLLIB3_LOG_LEVEL", "WARNING"))
    logging.getLogger("requests").setLevel(
        app.config.get("REQUESTS_LOG_LEVEL", "WARNING"))

    # -----------------------
    # Final banner (once)
    # -----------------------
    app.logger.info(
        "Logging configured: level=%s file=%s rotate=daily@localmidnight tz=%s console=%s",
        logging.getLevelName(level_num),
        logfile,
        tz_name,
        enable_console,
    )
    app.logger.warning(
        "### LOGGING CONFIGURED ### level=%s logfile=%s", level_num, logfile)
