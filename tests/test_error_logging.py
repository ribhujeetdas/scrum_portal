from __future__ import annotations

import json
import logging

from cryptography.fernet import Fernet

from app import create_app
from app.config import Config


class ErrorLoggingTestConfig(Config):
    TESTING = True
    PROPAGATE_EXCEPTIONS = False
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    FERNET_KEY = Fernet.generate_key().decode("ascii")
    LOG_TO_CONSOLE = False
    LOG_FILE = "test-app.log"


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


def test_unhandled_server_error_logs_stacktrace(tmp_path):
    class TestConfig(ErrorLoggingTestConfig):
        LOG_DIR = str(tmp_path)

    app = create_app(TestConfig)

    @app.route("/boom")
    def boom():
        raise RuntimeError("boom failure")

    response = app.test_client().get("/boom", headers={"X-Request-ID": "boom-123"})

    assert response.status_code == 500

    records = _read_json_lines(tmp_path / "test-app.log")
    errors = [record for record in records if record.get("event") == "error.unhandled"]

    assert errors
    assert errors[-1]["request_id"] == "boom-123"
    assert "boom failure" in errors[-1]["exception"]
    assert "Traceback" in errors[-1]["exception"]
