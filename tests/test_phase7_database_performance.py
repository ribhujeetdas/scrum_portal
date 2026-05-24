from __future__ import annotations

from pathlib import Path

from app import models

from tests.test_phase6_feature_routes_and_failures import (
    add_project,
    create_phase6_app,
    login,
    set_user_tokens,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations" / "versions"


def _migration_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(MIGRATIONS.glob("*.py"))
    )


def _index_names(table) -> set[str]:
    return {index.name for index in table.__table__.indexes}


def test_model_timestamps_use_timezone_aware_callable():
    assert "utcnow" not in Path(models.__file__).read_text(encoding="utf-8")
    now = models.utc_now()
    assert now.tzinfo is not None


def test_common_lookup_indexes_are_declared_on_models():
    assert "ix_user_boards_board_id" in _index_names(models.UserBoard)
    assert "ix_user_tableau_custom_views_user_updated" in _index_names(
        models.UserTableauCustomView
    )
    assert "ix_user_projects_project_id" in _index_names(models.UserProject)


def test_migrations_cover_project_id_and_phase7_indexes():
    text = _migration_text()

    assert "project_id" in text
    assert "ix_user_boards_board_id" in text
    assert "ix_user_tableau_custom_views_user_updated" in text
    assert "ix_user_projects_project_id" in text


class CountingJiraService:
    def __init__(self):
        self.calls = 0

    def fetch_myself(self, pat):
        self.calls += 1
        return {
            "emailAddress": "user@wellsfargo.com",
            "active": True,
            "deleted": False,
        }


class FakeRuleService:
    def get_rule_detail(self, project_identifier, rule_id, pat):
        return {"id": rule_id, "name": "Rule", "state": "ENABLED"}


def test_jira_pat_validation_is_cached_for_repeated_api_calls(tmp_path, monkeypatch):
    app = create_phase6_app(tmp_path)
    with app.app_context():
        set_user_tokens()
        add_project()

    import app.features.automation.rule_copier.routes as rule_routes

    jira = CountingJiraService()
    monkeypatch.setattr(rule_routes, "jira_service", lambda: jira)
    monkeypatch.setattr(rule_routes, "_rule_service", lambda: FakeRuleService())
    monkeypatch.setattr(
        rule_routes,
        "_ensure_project_id_for_user_project",
        lambda project_key, board_id, pat: 12345,
    )

    client = app.test_client()
    login(client)

    for _ in range(2):
        response = client.post(
            "/api/automation/rule-copier/fetch",
            json={"project_key": "ABC", "board_id": 101, "rule_id": 555},
        )
        assert response.status_code == 200

    assert jira.calls == 1
