from __future__ import annotations

from cryptography.fernet import Fernet

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User
from app.services.rule_copier_service import RuleCopierServiceError


class RuleCopyFallbackTestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    FERNET_KEY = Fernet.generate_key().decode("ascii")
    LOG_TO_CONSOLE = False
    LOG_FILE = "test-app.log"
    JIRA_AUTOMATION_ACTOR_ACCOUNT_ID = "SERVICE_ACTOR"


def create_rule_copy_app(tmp_path):
    class TestConfig(RuleCopyFallbackTestConfig):
        LOG_DIR = str(tmp_path)

    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        user = User(
            eid="E123",
            jira_key="USER_ACTOR",
            email="user@wellsfargo.com",
            display_name="Test User",
            active=True,
            deleted=False,
            password_hash="not-used",
        )
        db.session.add(user)
        db.session.commit()
    return app


def login_test_user(client, user_id=1):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


class FakeRuleService:
    def __init__(self):
        self.actor_attempts = []
        self.project_identifier_attempts = []

    def transform_rule_for_create(
        self,
        rule_json,
        target_project_id,
        author_account_id,
        actor_account_id,
    ):
        return {
            "name": rule_json["name"],
            "targetProjectId": target_project_id,
            "authorAccountId": author_account_id,
            "actorAccountId": actor_account_id,
        }

    def create_rule(self, project_identifier, payload, pat):
        self.project_identifier_attempts.append(project_identifier)
        self.actor_attempts.append(payload["actorAccountId"])
        if payload["actorAccountId"] == "SERVICE_ACTOR":
            raise RuleCopierServiceError("Create rule API error: actor rejected")
        return {"id": 987, "actor": payload["actorAccountId"]}


def test_copy_rule_falls_back_to_user_jira_actor_when_config_actor_fails(tmp_path, monkeypatch):
    app = create_rule_copy_app(tmp_path)
    fake_service = FakeRuleService()

    import app.features.automation.rule_copier.routes as rule_copier_routes

    monkeypatch.setattr(rule_copier_routes, "_get_user_pat", lambda: "pat")
    monkeypatch.setattr(rule_copier_routes, "_validate_pat_belongs_to_user", lambda pat: None)
    monkeypatch.setattr(
        rule_copier_routes,
        "_ensure_project_id_for_user_project",
        lambda project_key, board_id, pat: 12345,
    )
    monkeypatch.setattr(rule_copier_routes, "_rule_service", lambda: fake_service)

    client = app.test_client()
    login_test_user(client)

    response = client.post(
        "/automation/rule-copier/copy-rule",
        json={
            "target_project_key": "ABC",
            "target_board_id": 101,
            "rule_json": {"name": "Rule that rejects service actor"},
        },
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["created"]["actor"] == "USER_ACTOR"
    assert "SERVICE_ACTOR" in fake_service.actor_attempts
    assert "USER_ACTOR" in fake_service.actor_attempts
