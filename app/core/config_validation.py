from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet
from flask import Flask

from app import config as config_module

REQUIRED_INTEGRATION_SETTINGS = ("JIRA_BASE_URL", "TABLEAU_BASE_URL")
_PLACEHOLDER_SECRETS = {
    "",
    "change-me",
    "change-me-generated-fernet-key",
    "dev-secret-change-me",
    "secret",
    "test-secret",
}


class ConfigurationError(RuntimeError):
    def __init__(self, errors: Iterable[str]):
        self.errors = tuple(errors)
        super().__init__("Production configuration is invalid:\n- " + "\n- ".join(self.errors))


def _is_production(app: Flask) -> bool:
    return str(app.config.get("APP_ENV", "development")).lower() == "production"


def _valid_service_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and not (parsed.username or parsed.password)
    )


def sqlite_wal_is_safe(version: tuple[int, int, int] | None = None) -> bool:
    current = version or tuple(int(part) for part in sqlite3.sqlite_version.split(".")[:3])
    return current >= (3, 51, 3) or current in {(3, 50, 7), (3, 44, 6)}


def collect_config_errors(app: Flask) -> list[str]:
    errors = list(getattr(config_module, "_ENV_PARSE_ERRORS", ()))
    production = _is_production(app)

    secret_key = str(app.config.get("SECRET_KEY") or "").strip()
    if production and (
        secret_key.lower() in _PLACEHOLDER_SECRETS or len(secret_key.encode("utf-8")) < 32
    ):
        errors.append("SECRET_KEY must be a non-placeholder value of at least 32 bytes.")

    fernet_key = str(app.config.get("FERNET_KEY") or "").strip()
    if production and fernet_key.lower() in _PLACEHOLDER_SECRETS:
        errors.append("FERNET_KEY must be configured with a generated Fernet key.")
    elif fernet_key:
        try:
            Fernet(fernet_key.encode("ascii"))
        except (ValueError, TypeError):
            errors.append("FERNET_KEY is not a valid URL-safe base64 Fernet key.")

    database_url = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "").strip()
    if not database_url.startswith("sqlite:///"):
        errors.append("DATABASE_URL must use the supported sqlite:/// URL format.")
    elif production and database_url == "sqlite:///:memory:":
        errors.append("An in-memory SQLite database is not allowed in production.")

    for key in REQUIRED_INTEGRATION_SETTINGS:
        value = str(app.config.get(key, "") or "").strip()
        if production and not value:
            errors.append(f"{key} is required in production.")
        elif value and not _valid_service_url(value):
            errors.append(f"{key} must be an absolute HTTP(S) URL without credentials.")

    same_site = str(app.config.get("SESSION_COOKIE_SAMESITE", "Lax") or "").lower()
    if same_site not in {"lax", "strict", "none"}:
        errors.append("SESSION_COOKIE_SAMESITE must be Lax, Strict, or None.")
    if same_site == "none" and not app.config.get("SESSION_COOKIE_SECURE", False):
        errors.append("SESSION_COOKIE_SECURE must be true when SameSite=None.")

    retry_codes = str(app.config.get("EXTERNAL_HTTP_RETRY_STATUS_CODES", "") or "")
    try:
        parsed_codes = [int(part.strip()) for part in retry_codes.split(",") if part.strip()]
        if any(code < 400 or code > 599 for code in parsed_codes):
            raise ValueError
    except ValueError:
        errors.append("EXTERNAL_HTTP_RETRY_STATUS_CODES must contain HTTP 4xx/5xx codes.")

    metrics_mode = str(app.config.get("SPRINT_METRICS_MODE", "queued") or "").lower()
    if metrics_mode not in {"queued", "legacy"}:
        errors.append("SPRINT_METRICS_MODE must be queued or legacy.")

    journal_mode = str(app.config.get("SQLITE_JOURNAL_MODE", "DELETE") or "").upper()
    if journal_mode not in {"DELETE", "WAL"}:
        errors.append("SQLITE_JOURNAL_MODE must be DELETE or WAL.")
    if journal_mode == "WAL" and not sqlite_wal_is_safe():
        errors.append(
            f"SQLite {sqlite3.sqlite_version} is not approved for concurrent WAL use; "
            "use DELETE mode or a patched SQLite runtime."
        )

    synchronous = str(app.config.get("SQLITE_SYNCHRONOUS", "FULL") or "").upper()
    if synchronous not in {"OFF", "NORMAL", "FULL", "EXTRA"}:
        errors.append("SQLITE_SYNCHRONOUS must be OFF, NORMAL, FULL, or EXTRA.")
    if production and synchronous == "OFF":
        errors.append("SQLITE_SYNCHRONOUS=OFF is not allowed in production.")

    if production and not app.config.get("DATABASE_INSTANCE_LOCK", True):
        errors.append("DATABASE_INSTANCE_LOCK must be enabled in production.")
    if production and not app.config.get("RATE_LIMIT_ENABLED", True):
        errors.append("RATE_LIMIT_ENABLED must be enabled in production.")

    idle_minutes = int(app.config.get("SESSION_TIMEOUT_MINUTES", 15))
    absolute_minutes = int(app.config.get("SESSION_ABSOLUTE_MAX_MINUTES", 480))
    if absolute_minutes < idle_minutes:
        errors.append("SESSION_ABSOLUTE_MAX_MINUTES must not be shorter than the idle timeout.")

    log_format = str(app.config.get("LOG_FORMAT", "json") or "").lower()
    if log_format not in {"json", "text"}:
        errors.append("LOG_FORMAT must be json or text.")
    log_level = str(app.config.get("LOG_LEVEL", "INFO") or "").upper()
    if log_level not in logging.getLevelNamesMapping():
        errors.append("LOG_LEVEL is not a recognized Python logging level.")
    try:
        ZoneInfo(str(app.config.get("LOG_TIMEZONE", "Asia/Kolkata")))
    except ZoneInfoNotFoundError:
        errors.append("LOG_TIMEZONE must be a valid IANA timezone name.")
    log_file = str(app.config.get("LOG_FILE", "app.log") or "").strip()
    audit_file = str(app.config.get("AUDIT_LOG_FILE", "audit.log") or "").strip()
    if not log_file or Path(log_file).name != log_file:
        errors.append("LOG_FILE must be a file name without directory components.")
    if not audit_file or Path(audit_file).name != audit_file:
        errors.append("AUDIT_LOG_FILE must be a file name without directory components.")
    if log_file == audit_file:
        errors.append("LOG_FILE and AUDIT_LOG_FILE must be different files.")

    if production and not str(app.config.get("WAITRESS_HOST", "") or "").strip():
        errors.append("WAITRESS_HOST is required in production.")

    if production:
        log_dir = Path(str(app.config.get("LOG_DIR", "logs"))).expanduser()
        parent = log_dir if log_dir.exists() else log_dir.parent
        if not parent.exists() or not os.access(parent, os.W_OK):
            errors.append("LOG_DIR is not writable by the application process.")

    return list(dict.fromkeys(errors))


def collect_config_warnings(app: Flask) -> list[str]:
    warnings: list[str] = []
    for key in REQUIRED_INTEGRATION_SETTINGS:
        if not str(app.config.get(key, "") or "").strip():
            warnings.append(f"{key} is missing.")
    if str(app.config.get("SPRINT_METRICS_MODE", "queued") or "").lower() == "legacy":
        warnings.append(
            "SPRINT_METRICS_MODE=legacy is deprecated; use queued mode after diagnosis."
        )
    return warnings


def validate_config_or_raise(app: Flask) -> None:
    errors = collect_config_errors(app)
    if errors:
        raise ConfigurationError(errors)


def log_config_warnings(app: Flask, warnings: Iterable[str] | None = None) -> None:
    logger = logging.getLogger("app.config")
    for warning in list(warnings if warnings is not None else collect_config_warnings(app)):
        logger.warning("config warning: %s", warning, extra={"event": "config.warning"})
