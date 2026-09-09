# ===== FILE: config.py =====
from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    APP_ENV = os.getenv("APP_ENV", "development").lower()
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(2 * 1024 * 1024)))

    JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
    JIRA_ENABLED = os.getenv("JIRA_ENABLED", "true").lower() == "true"
    JIRA_SOURCE_ID = os.getenv("JIRA_SOURCE_ID", "primary-jira").strip()
    JIRA_STORY_POINTS_FIELD = os.getenv("JIRA_STORY_POINTS_FIELD", "customfield_10106")
    JIRA_APPLICATION_FIELD = os.getenv("JIRA_APPLICATION_FIELD", "customfield_11700")
    JIRA_EPIC_LINK_FIELD = os.getenv("JIRA_EPIC_LINK_FIELD", "customfield_10100")
    JIRA_HISTORY_VISIBILITY_FOLLOWS_ISSUE = (
        os.getenv("JIRA_HISTORY_VISIBILITY_FOLLOWS_ISSUE", "false").lower() == "true"
    )
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@wellsfargo.com")

    # Cookie & session security
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.getenv(
        "SESSION_COOKIE_SECURE", "true").lower() == "true"
    REMEMBER_COOKIE_SECURE = os.getenv(
        "REMEMBER_COOKIE_SECURE", "true").lower() == "true"
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")

    # CSRF
    WTF_CSRF_TIME_LIMIT = None  # let session lifetime govern it

    # Session timeout. Warning appears after this ratio is consumed.
    SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "15"))
    SESSION_WARNING_THRESHOLD_RATIO = float(
        os.getenv("SESSION_WARNING_THRESHOLD_RATIO", "0.8")
    )

    # PAT encryption
    FERNET_KEY = os.getenv("FERNET_KEY", "")

    # -----------------------
    # Logging (config-driven)
    # -----------------------
    # FIX: no trailing comma
    LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
    # relative to project root (we resolve in logging_conf)
    LOG_DIR = os.getenv("LOG_DIR", "logs")
    LOG_FILE = os.getenv("LOG_FILE", os.getenv("LOG_FILE_NAME", "app.log"))
    LOG_FILE_NAME = LOG_FILE
    LOG_BACKUPS = int(os.getenv("LOG_BACKUPS", os.getenv("LOG_BACKUP_DAYS", "14")))
    LOG_BACKUP_DAYS = LOG_BACKUPS

    # When true, also log to console (helpful in dev)
    LOG_TO_CONSOLE = os.getenv("LOG_TO_CONSOLE", "false").lower() == "true"
    LOG_CONSOLE = LOG_TO_CONSOLE

    # Use IST for timestamps + midnight rotation
    LOG_TIMEZONE = os.getenv("LOG_TIMEZONE", "Asia/Kolkata")
    LOG_TZ = LOG_TIMEZONE
    LOG_FORMAT = os.getenv("LOG_FORMAT", "json").lower()

    # Optional: make it easy to dial noisy libs down
    LOG_WERKZEUG_LEVEL = os.getenv("LOG_WERKZEUG_LEVEL", "INFO").upper()
    LOG_URLLIB3_LEVEL = os.getenv("LOG_URLLIB3_LEVEL", "WARNING").upper()
    LOG_SQLALCHEMY_LEVEL = os.getenv("LOG_SQLALCHEMY_LEVEL", "INFO").upper()
    REQUESTS_LOG_LEVEL = LOG_URLLIB3_LEVEL
    URLLIB3_LOG_LEVEL = LOG_URLLIB3_LEVEL
    WERKZEUG_LOG_LEVEL = LOG_WERKZEUG_LEVEL

    JIRA_AUTOMATION_ACTOR_ACCOUNT_ID = os.getenv(
        "JIRA_AUTOMATION_ACTOR_ACCOUNT_ID", "JIRAUSER182483"
    )
    JIRA_PAT_VALIDATION_CACHE_SECONDS = int(
        os.getenv("JIRA_PAT_VALIDATION_CACHE_SECONDS", "300")
    )

    EXTERNAL_HTTP_TIMEOUT_SECONDS = int(os.getenv("EXTERNAL_HTTP_TIMEOUT_SECONDS", "20"))
    EXTERNAL_HTTP_RETRY_TOTAL = int(os.getenv("EXTERNAL_HTTP_RETRY_TOTAL", "2"))
    EXTERNAL_HTTP_RETRY_BACKOFF_SECONDS = float(
        os.getenv("EXTERNAL_HTTP_RETRY_BACKOFF_SECONDS", "0.5")
    )
    EXTERNAL_HTTP_RETRY_STATUS_CODES = os.getenv(
        "EXTERNAL_HTTP_RETRY_STATUS_CODES", "429,500,502,503,504"
    )
    EXTERNAL_CA_BUNDLE = os.getenv("EXTERNAL_CA_BUNDLE", "").strip()
    EXTERNAL_TRUST_ENV = os.getenv("EXTERNAL_TRUST_ENV", "true").lower() == "true"
    HTTP_CONNECT_TIMEOUT_SECONDS = int(os.getenv("HTTP_CONNECT_TIMEOUT_SECONDS", "5"))
    HTTP_READ_TIMEOUT_SECONDS = int(os.getenv("HTTP_READ_TIMEOUT_SECONDS", str(EXTERNAL_HTTP_TIMEOUT_SECONDS)))
    HTTP_OPERATION_BUDGET_SECONDS = int(os.getenv("HTTP_OPERATION_BUDGET_SECONDS", "60"))
    HTTP_RETRY_AFTER_MAX_SECONDS = int(os.getenv("HTTP_RETRY_AFTER_MAX_SECONDS", "30"))
    HTTP_MAX_JSON_BYTES = int(os.getenv("HTTP_MAX_JSON_BYTES", str(16 * 1024 * 1024)))
    TABLEAU_MAX_CSV_BYTES = int(os.getenv("TABLEAU_MAX_CSV_BYTES", str(32 * 1024 * 1024)))

    LEGACY_ROUTE_DEPRECATION_HEADERS = (
        os.getenv("LEGACY_ROUTE_DEPRECATION_HEADERS", "true").lower() == "true"
    )
    LEGACY_ROUTE_SUNSET = os.getenv("LEGACY_ROUTE_SUNSET", "")

    SPRINT_METRICS_MAX_WORKERS = int(os.getenv("SPRINT_METRICS_MAX_WORKERS", "5"))
    SPRINT_METRICS_HTTP_TIMEOUT_SECONDS = int(
        os.getenv("SPRINT_METRICS_HTTP_TIMEOUT_SECONDS", str(EXTERNAL_HTTP_TIMEOUT_SECONDS))
    )
    SPRINT_VIEWER_MODE = os.getenv("SPRINT_VIEWER_MODE", "direct").lower()
    SPRINT_VIEWER_SNAPSHOT_USER_IDS = os.getenv("SPRINT_VIEWER_SNAPSHOT_USER_IDS", "")
    SPRINT_SNAPSHOT_ACCESS_POLICY = os.getenv("SPRINT_SNAPSHOT_ACCESS_POLICY", "jira_revalidate")
    SPRINT_JOB_LEASE_SECONDS = int(os.getenv("SPRINT_JOB_LEASE_SECONDS", "120"))
    SPRINT_JOB_HEARTBEAT_SECONDS = int(os.getenv("SPRINT_JOB_HEARTBEAT_SECONDS", "15"))
    SPRINT_JOB_MAX_ATTEMPTS = int(os.getenv("SPRINT_JOB_MAX_ATTEMPTS", "3"))
    SPRINT_JOB_POLL_SECONDS = float(os.getenv("SPRINT_JOB_POLL_SECONDS", "1"))
    SPRINT_WORKER_STALE_SECONDS = int(os.getenv("SPRINT_WORKER_STALE_SECONDS", "60"))
    JIRA_MAX_INFLIGHT_PER_SOURCE = int(os.getenv("JIRA_MAX_INFLIGHT_PER_SOURCE", "4"))
    JIRA_MAX_BACKGROUND_INFLIGHT = int(os.getenv("JIRA_MAX_BACKGROUND_INFLIGHT", "2"))
    SPRINT_COMPONENT_MAX_RUNTIME_SECONDS = int(
        os.getenv("SPRINT_COMPONENT_MAX_RUNTIME_SECONDS", "1800")
    )
    SQLITE_BUSY_TIMEOUT_MS = int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "5000"))
    SQLITE_WRITE_BUDGET_SECONDS = int(os.getenv("SQLITE_WRITE_BUDGET_SECONDS", "5"))
    TRUSTED_HOSTS = [
        host.strip()
        for host in os.getenv("TRUSTED_HOSTS", "").split(",")
        if host.strip()
    ]
    TRUSTED_PROXY_COUNT = int(os.getenv("TRUSTED_PROXY_COUNT", "0"))
    TABLEAU_ENABLED = os.getenv("TABLEAU_ENABLED", "true").lower() == "true"

    TRACE_SPRINT_VIEWER = os.getenv(
        "TRACE_SPRINT_VIEWER", "false").lower() == "true"
    TRACE_JIRA_JQL = os.getenv("TRACE_JIRA_JQL", "false").lower() == "true"

    # NEW: more granular tracing
    TRACE_SPRINT_VIEWER_API = os.getenv(
        "TRACE_SPRINT_VIEWER_API", "false").lower() == "true"
    TRACE_SPRINT_VIEWER_UI = os.getenv(
        "TRACE_SPRINT_VIEWER_UI", "false").lower() == "true"

    # -----------------------
    # NEW: Tableau REST API config
    # -----------------------
    TABLEAU_BASE_URL = os.getenv("TABLEAU_BASE_URL", "").rstrip("/")
    TABLEAU_API_VERSION = os.getenv("TABLEAU_API_VERSION", "3.7").strip()
    # Default site is typically contentUrl="", keep configurable
    TABLEAU_SITE_CONTENT_URL = os.getenv(
        "TABLEAU_SITE_CONTENT_URL", "").strip()
