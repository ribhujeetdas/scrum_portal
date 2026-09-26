from __future__ import annotations

from cryptography.fernet import Fernet

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User
from app.core.http_client import ExternalServiceError
from app.services.rule_copier_service import (
    RuleCopierDefinitiveRejection,
    RuleCopierDestinationSecretError,
    RuleCopierService,
    sanitize_sensitive_rule_data,
)


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


def test_rule_transform_reuses_component_ids_for_same_idempotency_key():
    service = RuleCopierService("https://jira.example.test")
    rule = {
        "name": "Deterministic rule",
        "components": [
            {"id": "__NEW__trigger"},
            {"children": [{"id": "__NEW__action"}]},
        ],
    }

    try:
        first = service.transform_rule_for_create(
            rule,
            target_project_id=123,
            author_account_id="author",
            actor_account_id="actor",
            idempotency_key="stable-operation-key",
        )
        second = service.transform_rule_for_create(
            rule,
            target_project_id=123,
            author_account_id="author",
            actor_account_id="actor",
            idempotency_key="stable-operation-key",
        )
    finally:
        service._client.close()

    assert first == second
    assert first["components"][0]["id"].startswith("__NEW__")
    assert first["components"][0]["id"] != first["components"][1]["children"][0]["id"]


def test_sensitive_values_are_replaced_while_keys_and_smart_values_are_preserved():
    rule = {
        "name": "Outbound request",
        "components": [
            {
                "type": "ACTION",
                "headers": [
                    {
                        "name": "Content-Type",
                        "value": {"keyOrValue": "application/json", "secret": False},
                    },
                    {"name": "Authorization", "value": "Bearer literal-secret"},
                    {"name": "X-API-Key", "value": "random-api-key-value"},
                    {"name": "X-Jira-Auth", "value": "{{secrets.jira_token}}"},
                    {"name": "X-Secret-Flag", "value": "opaque", "isSecret": True},
                ],
                "token": "another-literal-secret",
                "body": "safe body",
            }
        ],
    }

    sanitized, report = sanitize_sensitive_rule_data(rule)
    serialized = str(sanitized)

    headers = sanitized["components"][0]["headers"]
    assert headers[0]["value"] == {
        "keyOrValue": "application/json",
        "secret": False,
    }
    assert headers[1] == {
        "name": "Authorization",
        "value": "REPLACE_WITH_DESTINATION_CREDENTIAL",
    }
    assert headers[2] == {
        "name": "X-API-Key",
        "value": "REPLACE_WITH_DESTINATION_CREDENTIAL",
    }
    assert headers[3] == {
        "name": "X-Jira-Auth",
        "value": "{{secrets.jira_token}}",
    }
    assert headers[4]["name"] == "X-Secret-Flag"
    assert headers[4]["value"] == "REPLACE_WITH_DESTINATION_CREDENTIAL"
    assert sanitized["components"][0]["token"] == "REPLACE_WITH_DESTINATION_CREDENTIAL"
    assert "literal-secret" not in serialized
    assert "random-api-key-value" not in serialized
    assert "{{secrets.jira_token}}" in serialized
    assert report == {
        "redacted_count": 4,
        "redacted_header_names": [
            "Authorization",
            "X-API-Key",
            "X-Secret-Flag",
        ],
        "redacted_field_names": ["token"],
        "source_secret_names": [],
    }


def test_sensitive_header_keys_are_kept_with_nonempty_placeholders():
    rule = {
        "name": "Secret-only request",
        "components": [
            {
                "type": "ACTION",
                "headers": [
                    {"name": "Authorization", "value": "Bearer secret-value"},
                    {"name": "X-PAT", "value": "opaque-value"},
                ],
            }
        ],
    }

    sanitized, report = sanitize_sensitive_rule_data(rule)

    assert sanitized["components"][0]["headers"] == [
        {
            "name": "Authorization",
            "value": "REPLACE_WITH_DESTINATION_CREDENTIAL",
        },
        {"name": "X-PAT", "value": "REPLACE_WITH_DESTINATION_CREDENTIAL"},
    ]
    assert report["redacted_count"] == 2
    assert report["redacted_header_names"] == ["Authorization", "X-PAT"]


def test_data_center_managed_secret_is_replaced_but_smart_value_is_kept():
    rule = {
        "name": "Data Center secret examples",
        "components": [
            {
                "type": "jira.issue.outgoing.webhook",
                "value": {
                    "headers": [
                        {
                            "name": "Authorization",
                            "value": {
                                "keyOrValue": "{{jira_token}}",
                                "secret": False,
                            },
                        }
                    ],
                    "usedSecretsKeys": [],
                },
            },
            {
                "type": "jira.issue.outgoing.webhook",
                "value": {
                    "headers": [
                        {
                            "name": "Authorization",
                            "value": {
                                "keyOrValue": "jira_token",
                                "secret": True,
                            },
                        }
                    ],
                    "usedSecretsKeys": ["jira_token"],
                },
            },
        ],
    }

    sanitized, report = sanitize_sensitive_rule_data(rule)
    smart_header = sanitized["components"][0]["value"]["headers"][0]
    secret_config = sanitized["components"][1]["value"]
    secret_header = secret_config["headers"][0]

    assert smart_header["value"] == {
        "keyOrValue": "{{jira_token}}",
        "secret": False,
    }
    assert secret_header["name"] == "Authorization"
    assert secret_header["value"] == {
        "keyOrValue": "REPLACE_WITH_DESTINATION_CREDENTIAL",
        "secret": False,
    }
    assert secret_config["usedSecretsKeys"] == []
    assert report == {
        "redacted_count": 1,
        "redacted_header_names": ["Authorization"],
        "redacted_field_names": [],
        "source_secret_names": ["jira_token"],
    }


def test_sensitive_automation_variable_keeps_name_and_replaces_value():
    rule = {
        "name": "Variable example",
        "components": [
            {
                "component": "ACTION",
                "type": "jira.issue.create.variable",
                "value": {"name": "api_token", "value": "source-token-value"},
            },
            {
                "component": "ACTION",
                "type": "jira.issue.create.variable",
                "value": {"name": "ProjectKey", "value": "ABC"},
            },
        ],
    }

    sanitized, report = sanitize_sensitive_rule_data(rule)

    assert sanitized["components"][0]["value"] == {
        "name": "api_token",
        "value": "REPLACE_WITH_DESTINATION_CREDENTIAL",
    }
    assert sanitized["components"][1]["value"] == {
        "name": "ProjectKey",
        "value": "ABC",
    }
    assert "source-token-value" not in str(sanitized)
    assert report["redacted_field_names"] == ["api_token"]


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
        idempotency_key=None,
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
            raise RuleCopierDefinitiveRejection(
                "Create rule API rejected actor",
                fallback_kind="actor",
            )
        return {"id": 987, "actor": payload["actorAccountId"]}


class FakeRuleListHttpClient:
    def __init__(self, response):
        self.response = response

    def get_json(self, path, **_kwargs):
        assert path == "/rest/cb-automation/latest/project/123/rule"
        return self.response


class CompleteRuleListHttpClient:
    def __init__(self):
        self.paths = []

    def get_json(self, path, **_kwargs):
        self.paths.append(path)
        return {
            "rules": [
                {
                    "id": 35925,
                    "name": "Complete Data Center rule",
                    "components": [{"type": "ACTION"}],
                }
            ]
        }


def test_rule_list_supports_data_center_list_and_nested_response_shapes():
    expected = [{"id": 10, "name": "Rule"}]
    response_shapes = [
        expected,
        {"rules": expected},
        {"values": expected},
        {"rules": {"values": expected}},
    ]

    for response in response_shapes:
        service = RuleCopierService(
            "https://jira.example.test",
            http_client=FakeRuleListHttpClient(response),
        )
        assert service.list_rules_for_project(123, "pat") == expected


def test_rule_detail_prefers_complete_data_center_list_definition():
    client = CompleteRuleListHttpClient()
    service = RuleCopierService(
        "https://jira.example.test",
        http_client=client,
    )

    rule = service.get_rule_detail(112305, 35925, "pat")

    assert rule["name"] == "Complete Data Center rule"
    assert client.paths == [
        "/rest/cb-automation/latest/project/112305/rule"
    ]


def test_create_rule_error_identifies_unavailable_destination_secret():
    service = RuleCopierService("https://jira.example.test")
    error = ExternalServiceError(
        service="jira",
        operation="POST /rest/cb-automation/latest/project/123/rule",
        message="HTTP request failed",
        status_code=400,
        response_snippet=(
            '{"errors":{"component:4108061":{"headers":"A secret with key jira_token '
            'does not exist or is not allowed to be used with current scope."}},"status":400}'
        ),
        outcome="rejected",
    )

    try:
        service._raise_create_rule_error(error)
    except RuleCopierDestinationSecretError as exc:
        assert exc.secret_key == "jira_token"
        assert exc.definitive is True
        assert exc.outcome == "rejected"
    else:
        raise AssertionError("Expected destination secret error")


class SecretRejectedRuleService(FakeRuleService):
    def create_rule(self, project_identifier, payload, pat):
        raise RuleCopierDestinationSecretError("jira_token")


class RefetchingSensitiveRuleService:
    def __init__(self):
        self.source_requests = []
        self.created_payload = None
        self.transformer = RuleCopierService("https://jira.example.test")

    def get_rule_detail(self, project_identifier, rule_id, pat):
        self.source_requests.append((project_identifier, rule_id, pat))
        return {
            "id": rule_id,
            "name": "Rule with outbound request",
            "state": "ENABLED",
            "components": [
                {
                    "id": "source-component-id",
                    "value": {
                        "headers": [
                            {"name": "Content-Type", "value": "application/json"},
                            {
                                "name": "Authorization",
                                "value": {
                                    "keyOrValue": "server-only-secret",
                                    "secret": True,
                                },
                            },
                        ],
                        "usedSecretsKeys": ["server-only-secret"],
                    },
                }
            ],
        }

    def transform_rule_for_create(self, *args, **kwargs):
        return self.transformer.transform_rule_for_create(*args, **kwargs)

    def create_rule(self, project_identifier, payload, pat):
        self.created_payload = payload
        return {"id": 987}


def test_copy_rule_refetches_and_sanitizes_source_before_create(tmp_path, monkeypatch):
    app = create_rule_copy_app(tmp_path)
    fake_service = RefetchingSensitiveRuleService()

    import app.features.automation.rule_copier.routes as rule_copier_routes

    monkeypatch.setattr(rule_copier_routes, "_get_user_pat", lambda: "pat")
    monkeypatch.setattr(rule_copier_routes, "_validate_pat_belongs_to_user", lambda pat: None)
    monkeypatch.setattr(
        rule_copier_routes,
        "_ensure_project_id_for_user_project",
        lambda project_key, board_id, pat: 111 if project_key == "SRC" else 222,
    )
    monkeypatch.setattr(rule_copier_routes, "_rule_service", lambda: fake_service)

    client = app.test_client()
    login_test_user(client)
    try:
        response = client.post(
            "/api/automation/rule-copier/copy",
            json={
                "source_project_key": "SRC",
                "source_board_id": 101,
                "source_rule_id": 555,
                "target_project_key": "DST",
                "target_board_id": 202,
                "client_action_id": "server-refetch-sanitization-test",
            },
        )
    finally:
        fake_service.transformer._client.close()

    data = response.get_json()
    serialized_payload = str(fake_service.created_payload)

    assert response.status_code == 200
    assert fake_service.source_requests == [(111, 555, "pat")]
    assert "Authorization" in serialized_payload
    assert "server-only-secret" not in serialized_payload
    assert "REPLACE_WITH_DESTINATION_CREDENTIAL" in serialized_payload
    assert "Content-Type" in serialized_payload
    assert data["sanitization"] == {
        "redacted_count": 1,
        "redacted_header_names": ["Authorization"],
        "redacted_field_names": [],
        "source_secret_names": ["server-only-secret"],
    }
    assert "placeholder values for 1 sensitive entry" in data["message"]


def test_copy_rule_returns_actionable_destination_secret_error(tmp_path, monkeypatch):
    app = create_rule_copy_app(tmp_path)
    fake_service = SecretRejectedRuleService()

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
        "/api/automation/rule-copier/copy",
        json={
            "target_project_key": "BGKQ",
            "target_board_id": 41803,
            "rule_json": {"name": "Rule with secret"},
            "client_action_id": "destination-secret-test",
        },
    )
    data = response.get_json()

    assert response.status_code == 409
    assert data["error"]["code"] == "DESTINATION_SECRET_UNAVAILABLE"
    assert "details" not in data["error"]
    assert "destination project BGKQ" in data["error"]["message"]
    assert "Jira administrator" in data["error"]["message"]


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
            "client_action_id": "rule-copy-fallback-test",
        },
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["created"]["actor"] == "USER_ACTOR"
    assert "SERVICE_ACTOR" in fake_service.actor_attempts
    assert "USER_ACTOR" in fake_service.actor_attempts
