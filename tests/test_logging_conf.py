import json
import logging

from cryptography.fernet import Fernet

from app import create_app
from app.config import Config


class LoggingTestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    FERNET_KEY = Fernet.generate_key().decode("ascii")
    LOG_LEVEL = "INFO"
    LOG_TO_CONSOLE = False
    LOG_FILE = "test-app.log"


def _create_test_app(tmp_path):
    class TestConfig(LoggingTestConfig):
        LOG_DIR = str(tmp_path)

    return create_app(TestConfig)


def _flush_loggers():
    for logger in (logging.getLogger(), logging.getLogger("app")):
        for handler in logger.handlers:
            handler.flush()


def _read_json_lines(path):
    _flush_loggers()
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_request_id_is_returned_on_response(tmp_path):
    app = _create_test_app(tmp_path)

    response = app.test_client().get("/login")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_incoming_request_id_is_reused(tmp_path):
    app = _create_test_app(tmp_path)

    response = app.test_client().get(
        "/login", headers={"X-Request-ID": "ui-flow-123"}
    )

    assert response.headers["X-Request-ID"] == "ui-flow-123"


def test_request_completion_log_contains_correlation_fields(tmp_path):
    app = _create_test_app(tmp_path)

    app.test_client().get("/login", headers={"X-Request-ID": "audit-456"})

    records = _read_json_lines(tmp_path / "test-app.log")
    completion = next(
        record for record in records if record.get("event") == "request.complete"
    )
    assert completion["request_id"] == "audit-456"
    assert completion["method"] == "GET"
    assert completion["path"] == "/login"
    assert completion["endpoint"] == "auth.login"
    assert completion["status_code"] == 200
    assert isinstance(completion["duration_ms"], int)


def test_client_http_error_log_contains_server_diagnostics(tmp_path):
    app = _create_test_app(tmp_path)

    response = app.test_client().post(
        "/api/client-log",
        json={
            "event": "fetch.http_error",
            "message": "POST /automation/sprint-viewer/issues -> HTTP 403",
            "url": "http://localhost/automation/sprint-viewer?secret=discarded",
            "userAgent": "Test Browser",
            "method": "POST",
            "path": "/automation/sprint-viewer/issues",
            "statusCode": 403,
            "errorCode": "JIRA_PAT_REQUIRED",
            "requestId": "server-denied-123",
        },
    )

    assert response.status_code == 200
    records = _read_json_lines(tmp_path / "test-app.log")
    record = next(item for item in records if item.get("client_event") == "fetch.http_error")
    assert record["client_method"] == "POST"
    assert record["client_path"] == "/automation/sprint-viewer/issues"
    assert record["client_status_code"] == 403
    assert record["client_error_code"] == "JIRA_PAT_REQUIRED"
    assert record["client_request_id"] == "server-denied-123"
    assert "secret=discarded" not in json.dumps(record)
