from __future__ import annotations

import logging
import os
import re
from typing import Iterable
from urllib.parse import urlparse

from cryptography.fernet import Fernet

from flask import Flask


REQUIRED_INTEGRATION_SETTINGS = (
    "JIRA_BASE_URL",
    "TABLEAU_BASE_URL",
)


def collect_config_warnings(app: Flask) -> list[str]:
    warnings: list[str] = []
    for key in REQUIRED_INTEGRATION_SETTINGS:
        if not str(app.config.get(key, "") or "").strip():
            warnings.append(f"{key} is missing.")
    return warnings


def log_config_warnings(app: Flask, warnings: Iterable[str] | None = None) -> None:
    logger = logging.getLogger("app.config")
    for warning in list(warnings if warnings is not None else collect_config_warnings(app)):
        logger.warning("config warning: %s", warning, extra={"event": "config.warning"})


def validate_startup_config(app: Flask) -> None:
    app_env = str(app.config.get("APP_ENV") or "").lower()
    if app_env not in {"development", "test", "production"}:
        raise RuntimeError("APP_ENV must be development, test, or production")
    if app.config.get("TESTING") or app_env != "production":
        return
    failures: list[str] = []
    secret = str(app.config.get("SECRET_KEY") or "")
    if not secret or secret in {"dev-secret-change-me", "change-me"} or len(secret) < 32:
        failures.append("SECRET_KEY must be a non-placeholder value of at least 32 characters")
    fernet = str(app.config.get("FERNET_KEY") or "")
    try:
        Fernet(fernet.encode("ascii"))
    except Exception:
        failures.append("FERNET_KEY must be a valid Fernet key")
    if app.config.get("DEBUG"):
        failures.append("DEBUG must be disabled")
    if not app.config.get("SESSION_COOKIE_SECURE") or not app.config.get("REMEMBER_COOKIE_SECURE"):
        failures.append("session and remember cookies must be secure")
    if app.config.get("SESSION_COOKIE_SAMESITE") not in {"Lax", "Strict"}:
        failures.append("SESSION_COOKIE_SAMESITE must be Lax or Strict")
    if app.config.get("SPRINT_VIEWER_MODE") not in {"direct", "snapshot"}:
        failures.append("SPRINT_VIEWER_MODE must be direct or snapshot")
    if app.config.get("SPRINT_SNAPSHOT_ACCESS_POLICY") != "jira_revalidate":
        failures.append("SPRINT_SNAPSHOT_ACCESS_POLICY must be jira_revalidate")
    for enabled_key, url_key in (("JIRA_ENABLED", "JIRA_BASE_URL"), ("TABLEAU_ENABLED", "TABLEAU_BASE_URL")):
        if app.config.get(enabled_key):
            parsed = urlparse(str(app.config.get(url_key) or ""))
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                failures.append(f"{url_key} must be an HTTPS URL when {enabled_key} is enabled")
    if not str(app.config.get("JIRA_SOURCE_ID") or "").strip():
        failures.append("JIRA_SOURCE_ID is required")
    for field_name in ("JIRA_STORY_POINTS_FIELD", "JIRA_APPLICATION_FIELD", "JIRA_EPIC_LINK_FIELD"):
        if not re.fullmatch(r"customfield_[1-9][0-9]*", str(app.config.get(field_name) or "")):
            failures.append(f"{field_name} must use Jira customfield_<positive integer> format")
    bounded = {
        "HTTP_CONNECT_TIMEOUT_SECONDS": (1, 60),
        "HTTP_READ_TIMEOUT_SECONDS": (1, 300),
        "HTTP_OPERATION_BUDGET_SECONDS": (1, 900),
        "HTTP_RETRY_AFTER_MAX_SECONDS": (0, 300),
        "HTTP_MAX_JSON_BYTES": (1024, 64 * 1024 * 1024),
        "TABLEAU_MAX_CSV_BYTES": (1024, 128 * 1024 * 1024),
        "EXTERNAL_HTTP_RETRY_TOTAL": (0, 5),
        "SPRINT_JOB_LEASE_SECONDS": (15, 3600),
        "SPRINT_JOB_HEARTBEAT_SECONDS": (1, 300),
        "SPRINT_JOB_MAX_ATTEMPTS": (1, 10),
        "SPRINT_COMPONENT_MAX_RUNTIME_SECONDS": (30, 7200),
        "SQLITE_BUSY_TIMEOUT_MS": (100, 60000),
        "SQLITE_WRITE_BUDGET_SECONDS": (1, 60),
        "JIRA_MAX_INFLIGHT_PER_SOURCE": (2, 32),
        "JIRA_MAX_BACKGROUND_INFLIGHT": (1, 31),
        "MAX_CONTENT_LENGTH": (1024, 16 * 1024 * 1024),
        "TRUSTED_PROXY_COUNT": (0, 5),
        "SESSION_TIMEOUT_MINUTES": (1, 1440),
        "SESSION_WARNING_THRESHOLD_RATIO": (0.5, 0.95),
    }
    for name, (minimum, maximum) in bounded.items():
        value = app.config.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < minimum or value > maximum:
            failures.append(f"{name} must be between {minimum} and {maximum}")
    if app.config.get("JIRA_MAX_BACKGROUND_INFLIGHT", 0) >= app.config.get("JIRA_MAX_INFLIGHT_PER_SOURCE", 0):
        failures.append("JIRA_MAX_BACKGROUND_INFLIGHT must leave at least one interactive slot")
    if app.config.get("SPRINT_JOB_HEARTBEAT_SECONDS", 0) >= app.config.get("SPRINT_JOB_LEASE_SECONDS", 0):
        failures.append("SPRINT_JOB_HEARTBEAT_SECONDS must be below SPRINT_JOB_LEASE_SECONDS")
    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    if uri == "sqlite:///:memory:" or not uri.startswith("sqlite:///"):
        failures.append("Production DATABASE_URL must use a file-backed SQLite database")
    elif not os.path.isabs(uri.removeprefix("sqlite:///")):
        failures.append("Production SQLite database path must be absolute")
    elif uri.removeprefix("sqlite:///").startswith(("//", "\\\\")):
        failures.append("Production SQLite database must not use a network path")
    hosts = app.config.get("TRUSTED_HOSTS") or []
    if not hosts or any(host in {"*", "0.0.0.0"} for host in hosts):
        failures.append("TRUSTED_HOSTS is required")
    ca_bundle = str(app.config.get("EXTERNAL_CA_BUNDLE") or "").strip()
    if ca_bundle and (not os.path.isabs(ca_bundle) or not os.path.isfile(ca_bundle)):
        failures.append("EXTERNAL_CA_BUNDLE must be an existing absolute file")
    if failures:
        raise RuntimeError("Invalid production configuration: " + "; ".join(failures))
