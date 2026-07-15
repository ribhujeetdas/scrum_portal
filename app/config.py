from __future__ import annotations

import os
from typing import Final

from dotenv import load_dotenv

load_dotenv()

_ENV_PARSE_ERRORS: list[str] = []
_TRUE_VALUES: Final = {"1", "true", "yes", "on"}
_FALSE_VALUES: Final = {"0", "false", "no", "off"}


def _env_text(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None else value.strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    _ENV_PARSE_ERRORS.append(f"{name} must be one of: true, false, 1, 0, yes, no, on, off.")
    return default


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        _ENV_PARSE_ERRORS.append(f"{name} must be an integer.")
        return default
    if value < minimum or value > maximum:
        _ENV_PARSE_ERRORS.append(f"{name} must be between {minimum} and {maximum}.")
        return default
    return value


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except (TypeError, ValueError):
        _ENV_PARSE_ERRORS.append(f"{name} must be numeric.")
        return default
    if value < minimum or value > maximum:
        _ENV_PARSE_ERRORS.append(f"{name} must be between {minimum} and {maximum}.")
        return default
    return value


class Config:
    APP_ENV = _env_text("APP_ENV", "development").lower()
    APPLICATION_VERSION = _env_text("APPLICATION_VERSION", "dev")
    CONFIG_PARSE_ERRORS = tuple(_ENV_PARSE_ERRORS)

    SECRET_KEY = _env_text("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = _env_text("DATABASE_URL", "sqlite:///app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": _env_int("DATABASE_POOL_RECYCLE_SECONDS", 1800, minimum=60, maximum=86400),
        "connect_args": {
            "timeout": _env_int("SQLITE_CONNECT_TIMEOUT_SECONDS", 30, minimum=1, maximum=300)
        },
    }

    SQLITE_BUSY_TIMEOUT_MS = _env_int("SQLITE_BUSY_TIMEOUT_MS", 30000, minimum=100, maximum=300000)
    SQLITE_SYNCHRONOUS = _env_text("SQLITE_SYNCHRONOUS", "FULL").upper()
    SQLITE_JOURNAL_MODE = _env_text("SQLITE_JOURNAL_MODE", "DELETE").upper()
    SQLITE_MINIMUM_SAFE_WAL_VERSION = (3, 51, 3)
    SQLITE_WRITE_RETRY_TOTAL = _env_int("SQLITE_WRITE_RETRY_TOTAL", 2, minimum=0, maximum=5)
    SQLITE_WRITE_RETRY_BACKOFF_SECONDS = _env_float(
        "SQLITE_WRITE_RETRY_BACKOFF_SECONDS", 0.05, minimum=0.0, maximum=2.0
    )
    DATABASE_INSTANCE_LOCK = _env_bool("DATABASE_INSTANCE_LOCK", True)
    DATABASE_BACKUP_DIR = _env_text("DATABASE_BACKUP_DIR", "backups")
    DATABASE_BACKUP_RETENTION = _env_int("DATABASE_BACKUP_RETENTION", 14, minimum=1, maximum=365)

    JIRA_BASE_URL = _env_text("JIRA_BASE_URL").rstrip("/")
    ADMIN_EMAIL = _env_text("ADMIN_EMAIL", "admin@example.com")

    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", False)
    REMEMBER_COOKIE_SECURE = _env_bool("REMEMBER_COOKIE_SECURE", False)
    SESSION_COOKIE_SAMESITE = _env_text("SESSION_COOKIE_SAMESITE", "Lax")
    WTF_CSRF_TIME_LIMIT = _env_int("WTF_CSRF_TIME_LIMIT_SECONDS", 3600, minimum=300, maximum=86400)

    SESSION_TIMEOUT_MINUTES = _env_int("SESSION_TIMEOUT_MINUTES", 15, minimum=1, maximum=1440)
    SESSION_ABSOLUTE_MAX_MINUTES = _env_int(
        "SESSION_ABSOLUTE_MAX_MINUTES", 480, minimum=1, maximum=10080
    )
    SESSION_WARNING_THRESHOLD_RATIO = _env_float(
        "SESSION_WARNING_THRESHOLD_RATIO", 0.8, minimum=0.1, maximum=0.95
    )
    SIGNUP_STATE_TTL_MINUTES = _env_int("SIGNUP_STATE_TTL_MINUTES", 20, minimum=1, maximum=120)

    FERNET_KEY = _env_text("FERNET_KEY")

    LOG_LEVEL = _env_text("LOG_LEVEL", "INFO").upper()
    LOG_DIR = _env_text("LOG_DIR", "logs")
    LOG_FILE = _env_text("LOG_FILE", _env_text("LOG_FILE_NAME", "app.log"))
    LOG_FILE_NAME = LOG_FILE
    LOG_BACKUPS = _env_int("LOG_BACKUPS", 14, minimum=1, maximum=365)
    LOG_BACKUP_DAYS = LOG_BACKUPS
    AUDIT_LOG_FILE = _env_text("AUDIT_LOG_FILE", "audit.log")
    AUDIT_LOG_BACKUPS = _env_int("AUDIT_LOG_BACKUPS", 30, minimum=1, maximum=730)
    LOG_TO_CONSOLE = _env_bool("LOG_TO_CONSOLE", False)
    LOG_CONSOLE = LOG_TO_CONSOLE
    LOG_TIMEZONE = _env_text("LOG_TIMEZONE", "Asia/Kolkata")
    LOG_TZ = LOG_TIMEZONE
    LOG_FORMAT = _env_text("LOG_FORMAT", "json").lower()
    LOG_WERKZEUG_LEVEL = _env_text("LOG_WERKZEUG_LEVEL", "WARNING").upper()
    LOG_URLLIB3_LEVEL = _env_text("LOG_URLLIB3_LEVEL", "WARNING").upper()
    LOG_SQLALCHEMY_LEVEL = _env_text("LOG_SQLALCHEMY_LEVEL", "WARNING").upper()
    REQUESTS_LOG_LEVEL = LOG_URLLIB3_LEVEL
    URLLIB3_LOG_LEVEL = LOG_URLLIB3_LEVEL
    WERKZEUG_LOG_LEVEL = LOG_WERKZEUG_LEVEL

    JIRA_AUTOMATION_ACTOR_ACCOUNT_ID = _env_text(
        "JIRA_AUTOMATION_ACTOR_ACCOUNT_ID", "JIRAUSER_SERVICE_ACCOUNT"
    )
    JIRA_PAT_VALIDATION_CACHE_SECONDS = _env_int(
        "JIRA_PAT_VALIDATION_CACHE_SECONDS", 300, minimum=0, maximum=3600
    )

    EXTERNAL_HTTP_TIMEOUT_SECONDS = _env_int(
        "EXTERNAL_HTTP_TIMEOUT_SECONDS", 20, minimum=1, maximum=120
    )
    EXTERNAL_HTTP_CONNECT_TIMEOUT_SECONDS = _env_int(
        "EXTERNAL_HTTP_CONNECT_TIMEOUT_SECONDS", 5, minimum=1, maximum=60
    )
    EXTERNAL_HTTP_RETRY_TOTAL = _env_int("EXTERNAL_HTTP_RETRY_TOTAL", 3, minimum=0, maximum=8)
    EXTERNAL_HTTP_RETRY_BACKOFF_SECONDS = _env_float(
        "EXTERNAL_HTTP_RETRY_BACKOFF_SECONDS", 0.5, minimum=0.0, maximum=10.0
    )
    EXTERNAL_HTTP_RETRY_STATUS_CODES = _env_text(
        "EXTERNAL_HTTP_RETRY_STATUS_CODES", "429,500,502,503,504"
    )
    EXTERNAL_HTTP_MAX_CONCURRENT = _env_int(
        "EXTERNAL_HTTP_MAX_CONCURRENT", 12, minimum=1, maximum=64
    )
    EXTERNAL_HTTP_BULKHEAD_WAIT_SECONDS = _env_float(
        "EXTERNAL_HTTP_BULKHEAD_WAIT_SECONDS", 1.0, minimum=0.0, maximum=30.0
    )
    EXTERNAL_HTTP_CIRCUIT_FAILURE_THRESHOLD = _env_int(
        "EXTERNAL_HTTP_CIRCUIT_FAILURE_THRESHOLD", 5, minimum=1, maximum=50
    )
    EXTERNAL_HTTP_CIRCUIT_RESET_SECONDS = _env_int(
        "EXTERNAL_HTTP_CIRCUIT_RESET_SECONDS", 30, minimum=1, maximum=3600
    )
    EXTERNAL_OPERATION_MAX_PAGES = _env_int(
        "EXTERNAL_OPERATION_MAX_PAGES", 100, minimum=1, maximum=1000
    )
    EXTERNAL_OPERATION_DEADLINE_SECONDS = _env_int(
        "EXTERNAL_OPERATION_DEADLINE_SECONDS", 120, minimum=5, maximum=3600
    )

    RATE_LIMIT_ENABLED = _env_bool("RATE_LIMIT_ENABLED", True)
    RATE_LIMIT_LOGIN_ATTEMPTS = _env_int("RATE_LIMIT_LOGIN_ATTEMPTS", 8, minimum=1, maximum=100)
    RATE_LIMIT_LOGIN_WINDOW_SECONDS = _env_int(
        "RATE_LIMIT_LOGIN_WINDOW_SECONDS", 300, minimum=10, maximum=86400
    )
    RATE_LIMIT_EXPENSIVE_ATTEMPTS = _env_int(
        "RATE_LIMIT_EXPENSIVE_ATTEMPTS", 20, minimum=1, maximum=1000
    )
    RATE_LIMIT_EXPENSIVE_WINDOW_SECONDS = _env_int(
        "RATE_LIMIT_EXPENSIVE_WINDOW_SECONDS", 60, minimum=1, maximum=3600
    )

    LEGACY_ROUTE_DEPRECATION_HEADERS = _env_bool("LEGACY_ROUTE_DEPRECATION_HEADERS", True)
    LEGACY_ROUTE_SUNSET = _env_text("LEGACY_ROUTE_SUNSET")

    SPRINT_METRICS_MAX_WORKERS = _env_int("SPRINT_METRICS_MAX_WORKERS", 3, minimum=1, maximum=5)
    SPRINT_METRICS_HTTP_TIMEOUT_SECONDS = _env_int(
        "SPRINT_METRICS_HTTP_TIMEOUT_SECONDS",
        EXTERNAL_HTTP_TIMEOUT_SECONDS,
        minimum=1,
        maximum=120,
    )

    # Configurable bind-all is intentional for the approved local multi-user topology.
    WAITRESS_HOST = _env_text("WAITRESS_HOST", "0.0.0.0")  # nosec B104
    WAITRESS_PORT = _env_int("WAITRESS_PORT", 5000, minimum=1, maximum=65535)
    WAITRESS_THREADS = _env_int("WAITRESS_THREADS", 4, minimum=1, maximum=32)
    WAITRESS_CONNECTION_LIMIT = _env_int(
        "WAITRESS_CONNECTION_LIMIT", 100, minimum=10, maximum=10000
    )
    WAITRESS_CHANNEL_TIMEOUT_SECONDS = _env_int(
        "WAITRESS_CHANNEL_TIMEOUT_SECONDS", 120, minimum=10, maximum=3600
    )
    MAX_CONTENT_LENGTH = _env_int(
        "MAX_CONTENT_LENGTH_BYTES", 2 * 1024 * 1024, minimum=8192, maximum=50 * 1024 * 1024
    )
    MIN_FREE_DISK_MB = _env_int("MIN_FREE_DISK_MB", 256, minimum=32, maximum=102400)

    TRACE_SPRINT_VIEWER = _env_bool("TRACE_SPRINT_VIEWER", False)
    TRACE_JIRA_JQL = _env_bool("TRACE_JIRA_JQL", False)
    TRACE_SPRINT_VIEWER_API = _env_bool("TRACE_SPRINT_VIEWER_API", False)
    TRACE_SPRINT_VIEWER_UI = _env_bool("TRACE_SPRINT_VIEWER_UI", False)

    TABLEAU_BASE_URL = _env_text("TABLEAU_BASE_URL").rstrip("/")
    TABLEAU_API_VERSION = _env_text("TABLEAU_API_VERSION", "3.25")
    TABLEAU_SITE_CONTENT_URL = _env_text("TABLEAU_SITE_CONTENT_URL")


class DevelopmentConfig(Config):
    APP_ENV = "development"
    DEBUG = True


class TestingConfig(Config):
    APP_ENV = "testing"
    TESTING = True
    WTF_CSRF_ENABLED = False
    DATABASE_INSTANCE_LOCK = False


class ProductionConfig(Config):
    APP_ENV = "production"
    DEBUG = False
    TESTING = False


CONFIG_BY_ENV = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
