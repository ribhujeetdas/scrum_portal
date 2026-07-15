from __future__ import annotations

import json
import sqlite3
from contextlib import closing

import pytest
from cryptography.fernet import Fernet
from flask import Flask

from app.core.config_validation import (
    ConfigurationError,
    collect_config_errors,
    collect_config_warnings,
    sqlite_wal_is_safe,
    validate_config_or_raise,
)
from app.core.database import DatabaseInstanceLock
from app.core.datetime_utils import parse_external_datetime, to_iso8601
from app.core.http_client import ExternalOperationBudget, ExternalServiceError
from app.core.rate_limit import InMemoryRateLimiter, RateLimitExceeded
from scripts.database_common import backup_database, prune_backups, restore_database


def _production_app(tmp_path, **overrides) -> Flask:
    app = Flask(__name__)
    app.config.update(
        APP_ENV="production",
        SECRET_KEY="s" * 48,
        FERNET_KEY=Fernet.generate_key().decode("ascii"),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'portal.sqlite3'}",
        JIRA_BASE_URL="https://jira.example",
        TABLEAU_BASE_URL="https://tableau.example",
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,
        EXTERNAL_HTTP_RETRY_STATUS_CODES="429,500,502,503,504",
        SQLITE_JOURNAL_MODE="DELETE",
        SQLITE_SYNCHRONOUS="FULL",
        WAITRESS_HOST="127.0.0.1",
        LOG_FORMAT="json",
        LOG_FILE="app.log",
        AUDIT_LOG_FILE="audit.log",
        LOG_DIR=str(tmp_path),
    )
    app.config.update(overrides)
    return app


def test_production_configuration_accepts_strong_explicit_values(tmp_path):
    assert collect_config_errors(_production_app(tmp_path)) == []


def test_production_configuration_rejects_placeholder_secrets(tmp_path):
    app = _production_app(
        tmp_path,
        SECRET_KEY="change-me",
        FERNET_KEY="change-me-generated-fernet-key",
    )

    errors = collect_config_errors(app)

    assert any("SECRET_KEY" in error for error in errors)
    assert any("FERNET_KEY" in error for error in errors)


def test_production_configuration_requires_integration_origins(tmp_path):
    app = _production_app(tmp_path, JIRA_BASE_URL="", TABLEAU_BASE_URL="")

    errors = collect_config_errors(app)

    assert "JIRA_BASE_URL is required in production." in errors
    assert "TABLEAU_BASE_URL is required in production." in errors


def test_production_configuration_rejects_unsafe_runtime_settings(tmp_path):
    app = _production_app(
        tmp_path,
        SQLALCHEMY_DATABASE_URI="postgresql://database.example/portal",
        JIRA_BASE_URL="ftp://jira.example",
        TABLEAU_BASE_URL="https://user:password@tableau.example",
        SESSION_COOKIE_SAMESITE="None",
        SESSION_COOKIE_SECURE=False,
        EXTERNAL_HTTP_RETRY_STATUS_CODES="200,503",
        SQLITE_JOURNAL_MODE="BROKEN",
        SQLITE_SYNCHRONOUS="OFF",
        DATABASE_INSTANCE_LOCK=False,
        RATE_LIMIT_ENABLED=False,
        SESSION_TIMEOUT_MINUTES=60,
        SESSION_ABSOLUTE_MAX_MINUTES=30,
        LOG_FORMAT="yaml",
        LOG_LEVEL="LOUD",
        LOG_TIMEZONE="Mars/Olympus",
        LOG_FILE="../app.log",
        AUDIT_LOG_FILE="",
        WAITRESS_HOST="",
        LOG_DIR=str(tmp_path / "missing" / "logs"),
    )

    errors = collect_config_errors(app)

    expected_fragments = (
        "DATABASE_URL",
        "JIRA_BASE_URL",
        "TABLEAU_BASE_URL",
        "SESSION_COOKIE_SECURE",
        "EXTERNAL_HTTP_RETRY_STATUS_CODES",
        "SQLITE_JOURNAL_MODE",
        "SQLITE_SYNCHRONOUS=OFF",
        "DATABASE_INSTANCE_LOCK",
        "RATE_LIMIT_ENABLED",
        "SESSION_ABSOLUTE_MAX_MINUTES",
        "LOG_FORMAT",
        "LOG_LEVEL",
        "LOG_TIMEZONE",
        "LOG_FILE",
        "AUDIT_LOG_FILE",
        "WAITRESS_HOST",
        "LOG_DIR",
    )
    for fragment in expected_fragments:
        assert any(fragment in error for error in errors)


def test_config_warning_and_validation_helpers(tmp_path):
    app = _production_app(tmp_path, JIRA_BASE_URL="", TABLEAU_BASE_URL="")

    assert collect_config_warnings(app) == [
        "JIRA_BASE_URL is missing.",
        "TABLEAU_BASE_URL is missing.",
    ]
    with pytest.raises(ConfigurationError, match="Production configuration is invalid"):
        validate_config_or_raise(app)


@pytest.mark.parametrize(
    ("version", "safe"),
    [
        ((3, 49, 1), False),
        ((3, 44, 6), True),
        ((3, 50, 7), True),
        ((3, 51, 2), False),
        ((3, 51, 3), True),
    ],
)
def test_wal_safety_gate_accounts_for_fixed_backports(version, safe):
    assert sqlite_wal_is_safe(version) is safe


def test_instance_lock_rejects_a_second_server_for_the_same_database(tmp_path):
    database = tmp_path / "portal.sqlite3"
    database.touch()
    first = DatabaseInstanceLock(database)
    second = DatabaseInstanceLock(database)
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="Another application process"):
            second.acquire()
    finally:
        first.release()


def test_backup_uses_sqlite_online_api_and_writes_verified_metadata(tmp_path):
    source = tmp_path / "portal.sqlite3"
    with closing(sqlite3.connect(source)) as connection, connection:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample(value) VALUES ('original')")

    backup, metadata_path = backup_database(source, tmp_path / "backups")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert metadata["integrity_ok"] is True
    assert metadata["foreign_key_ok"] is True
    assert len(metadata["sha256"]) == 64
    with closing(sqlite3.connect(backup)) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "original"

    assert prune_backups(backup.parent, source.stem, retention=0) == [backup]
    assert not metadata_path.exists()


def test_backup_refuses_to_create_an_empty_database_for_a_missing_source(tmp_path):
    source = tmp_path / "missing.sqlite3"
    with pytest.raises(FileNotFoundError):
        backup_database(source, tmp_path / "backups")
    assert not source.exists()


def test_restore_verifies_and_atomically_replaces_database(tmp_path):
    target = tmp_path / "portal.sqlite3"
    desired = tmp_path / "desired.sqlite3"
    for path, value in ((target, "current"), (desired, "restored")):
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
            connection.execute("INSERT INTO sample(value) VALUES (?)", (value,))
    backup, _metadata = backup_database(desired, tmp_path / "source-backups")

    safety_backup = restore_database(target, backup, tmp_path / "safety-backups")

    with closing(sqlite3.connect(target)) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "restored"
    with closing(sqlite3.connect(safety_backup)) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone()[0] == "current"


def test_rate_limiter_blocks_and_can_reset_a_subject():
    limiter = InMemoryRateLimiter()
    limiter.check(scope="login", key="subject", limit=1, window_seconds=60)
    with pytest.raises(RateLimitExceeded):
        limiter.check(scope="login", key="subject", limit=1, window_seconds=60)
    limiter.reset(scope="login", key="subject")
    limiter.check(scope="login", key="subject", limit=1, window_seconds=60)


def test_external_operation_budget_bounds_pagination():
    budget = ExternalOperationBudget("jira", "test pagination", max_pages=1, deadline_seconds=60)
    budget.next_page()
    with pytest.raises(ExternalServiceError) as raised:
        budget.next_page()
    assert raised.value.category == "operation_budget_exceeded"


def test_external_datetime_round_trip_is_timezone_aware():
    parsed = parse_external_datetime("2026-01-15T10:20:30.000+0000")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert to_iso8601(parsed) == "2026-01-15T10:20:30+00:00"
