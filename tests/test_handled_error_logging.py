from __future__ import annotations

import json
import logging

from cryptography.fernet import Fernet

from app import create_app
from app.config import Config
from app.core.error_logging import log_handled_exception
from app.extensions import db
from app.models import User, UserBoard, UserProject
from app.services.sprint_viewer_service import SprintViewerServiceError


class HandledErrorLoggingTestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    FERNET_KEY = Fernet.generate_key().decode("ascii")
    LOG_TO_CONSOLE = False
    LOG_FILE = "test-app.log"


def _create_test_app(tmp_path):
    class TestConfig(HandledErrorLoggingTestConfig):
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


def _login(client, user_id=1):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def _add_user_project_and_board():
    user = User(
        eid="E123",
        jira_key="JIRAUSER1",
        email="user@wellsfargo.com",
        display_name="Test User",
        active=True,
        deleted=False,
        password_hash="not-used",
    )
    db.session.add(user)
    db.session.flush()
    project = UserProject(user_id=user.id, project_key="ABC", admin_projects=True)
    db.session.add(project)
    db.session.flush()
    db.session.add(
        UserBoard(
            project_id=project.id,
            board_id=101,
            board_name="ABC Board",
            board_type="scrum",
            board_url="https://jira.example/boards/101",
        )
    )
    db.session.commit()


def test_log_handled_exception_writes_stacktrace_and_sanitized_context(tmp_path):
    app = _create_test_app(tmp_path)

    @app.route("/handled-error")
    def handled_error():
        try:
            raise RuntimeError("PAT token=super-secret failed")
        except RuntimeError as exc:
            log_handled_exception(
                "Handled service failure",
                exc,
                event="test.handled.failure",
                feature="test_feature",
                operation="exercise_logger",
                context={"project_key": "ABC", "pat_token": "super-secret"},
            )
            return "handled", 400

    response = app.test_client().get(
        "/handled-error", headers={"X-Request-ID": "handled-123"}
    )

    assert response.status_code == 400

    records = _read_json_lines(tmp_path / "test-app.log")
    record = next(r for r in records if r.get("event") == "test.handled.failure")

    assert record["request_id"] == "handled-123"
    assert record["feature"] == "test_feature"
    assert record["operation"] == "exercise_logger"
    assert record["error_type"] == "RuntimeError"
    assert "Traceback" in record["exception"]
    assert "super-secret" not in json.dumps(record)
    assert record["context"] == {"project_key": "ABC", "pat_token": "<redacted>"}


class FailingSprintService:
    def fetch_all_issues_for_sprint(self, sprint_id, pat):
        raise SprintViewerServiceError("Sprint API error: 500 pat_token=super-secret")


def test_sprint_viewer_service_error_is_logged_with_stacktrace(tmp_path, monkeypatch):
    app = _create_test_app(tmp_path)
    with app.app_context():
        db.create_all()
        _add_user_project_and_board()

    import app.features.automation.sprint_viewer.routes as sprint_viewer_routes

    monkeypatch.setattr(sprint_viewer_routes, "_get_user_pat", lambda: "pat")
    monkeypatch.setattr(sprint_viewer_routes, "_validate_pat_belongs_to_user", lambda pat: None)
    monkeypatch.setattr(sprint_viewer_routes, "_sprint_service", lambda: FailingSprintService())

    client = app.test_client()
    _login(client)

    response = client.post(
        "/automation/sprint-viewer/issues",
        json={"board_id": 101, "sprint_id": 202},
        headers={"X-Request-ID": "sprint-err-123"},
    )

    assert response.status_code == 400

    records = _read_json_lines(tmp_path / "test-app.log")
    record = next(
        r for r in records if r.get("event") == "automation.sprint_viewer.issues_failed"
    )

    assert record["request_id"] == "sprint-err-123"
    assert record["feature"] == "sprint_viewer"
    assert record["operation"] == "fetch_issues"
    assert record["error_type"] == "SprintViewerServiceError"
    assert "Traceback" in record["exception"]
    assert "super-secret" not in json.dumps(record)
