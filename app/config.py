# ===== FILE: config.py =====
from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "").rstrip("/")
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
