from __future__ import annotations

import logging
from pathlib import Path

from app.models import UserBoard, UserProject
from app.services.jira_projects_service import (
    JiraProjectsService,
    JiraProjectsServiceError,
)
from tests.test_phase6_feature_routes_and_failures import (
    create_phase6_app,
    login,
    set_user_tokens,
)


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_shows_only_renamed_sprint_viewer_card(tmp_path):
    app = create_phase6_app(tmp_path)
    client = app.test_client()
    login(client)

    html = client.get("/dashboard").get_data(as_text=True)

    assert html.count('class="card-title"') == 1
    assert ">Sprint Viewer<" in html
    assert "Closed Sprint Viewer" not in html
    assert "Jira Automation Rule Copier" not in html
    assert "TCI Reports" not in html
    assert ">Planning<" not in html


def test_hidden_dashboard_cards_are_reversible_with_config_flag(tmp_path):
    app = create_phase6_app(tmp_path)
    app.config["SHOW_HIDDEN_DASHBOARD_FEATURES"] = True
    client = app.test_client()
    login(client)

    html = client.get("/dashboard").get_data(as_text=True)

    assert "Jira Automation Rule Copier" in html
    assert "TCI Reports" in html
    assert ">Planning<" in html


def test_settings_shows_only_enterprise_jira_and_redirects_hidden_routes(tmp_path):
    app = create_phase6_app(tmp_path)
    client = app.test_client()
    login(client)

    response = client.get("/settings/integrations")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Enterprise Agile Jira Configuration" in html
    assert "Tableau Configuration" not in html
    assert ">Integrations<" in html
    assert "Projects & Boards" not in html
    assert "Projects &amp; Boards" not in html
    assert "Tableau Custom Views" not in html

    for path in (
        "/settings/projects-boards",
        "/settings/tableau-custom-views",
        "/config/projects",
        "/config/custom-views",
    ):
        hidden_response = client.get(path, follow_redirects=False)
        assert hidden_response.status_code == 302, path
        assert hidden_response.headers["Location"].endswith("/settings/integrations"), path


def test_hidden_settings_are_reversible_with_config_flag(tmp_path):
    app = create_phase6_app(tmp_path)
    app.config["SHOW_HIDDEN_SETTINGS_FEATURES"] = True
    client = app.test_client()
    login(client)

    html = client.get("/settings/integrations").get_data(as_text=True)

    assert "Tableau Configuration" in html
    assert 'href="/settings/projects-boards"' in html
    assert 'href="/settings/tableau-custom-views"' in html
    assert client.get("/settings/projects-boards").status_code == 200


def test_sprint_viewer_initial_controls_are_sequential_and_pat_is_not_rendered(tmp_path):
    app = create_phase6_app(tmp_path)
    with app.app_context():
        set_user_tokens()

    client = app.test_client()
    login(client)
    response = client.get("/automation/sprint-viewer")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<input id="projectKey"' in html
    assert '<select id="projectKey"' not in html
    assert '<select id="boardId"' in html
    assert '<select id="boardId" class="form-select" aria-describedby="boardStatus" disabled>' in html
    assert '<select id="sprintId" class="form-select" aria-describedby="sprintStatus" disabled>' in html
    assert "jira-pat" not in html


class _AccessibleProjectsService:
    def __init__(self, boards=None):
        self.boards = boards if boards is not None else [
            {
                "board_id": 202,
                "board_name": "Delivery Board",
                "board_type": "scrum",
                "board_url": "https://jira.example/boards/202",
            },
            {
                "board_id": 101,
                "board_name": "Alpha Board",
                "board_type": "scrum",
                "board_url": "https://jira.example/boards/101",
            },
        ]
        self.permission_calls = []
        self.board_calls = []

    def has_browse_projects(self, project_key, pat):
        self.permission_calls.append((project_key, pat))
        return True

    def list_boards_for_project(self, project_key, pat):
        self.board_calls.append((project_key, pat))
        return self.boards


def test_valid_project_key_loads_selection_only_boards_and_upserts_associations(
    tmp_path, monkeypatch
):
    app = create_phase6_app(tmp_path)
    with app.app_context():
        set_user_tokens()

    service = _AccessibleProjectsService()
    import app.features.automation.sprint_viewer.routes as sprint_routes

    monkeypatch.setattr(sprint_routes, "jira_projects_service", lambda: service)
    monkeypatch.setattr(sprint_routes, "_validate_pat_belongs_to_user", lambda pat: None)

    client = app.test_client()
    login(client)
    response = client.post(
        "/api/automation/sprint-viewer/boards",
        json={"project_key": " abc1 "},
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["project_key"] == "ABC1"
    assert [board["board_id"] for board in data["boards"]] == [101, 202]
    assert service.permission_calls == [("ABC1", "jira-pat")]
    assert service.board_calls == [("ABC1", "jira-pat")]
    assert "jira-pat" not in response.get_data(as_text=True)

    with app.app_context():
        project = UserProject.query.filter_by(user_id=1, project_key="ABC1").one()
        assert project.admin_projects is False
        assert {
            board.board_id
            for board in UserBoard.query.filter_by(project_id=project.id).all()
        } == {101, 202}


def test_invalid_and_unauthorized_project_keys_keep_boards_unavailable(
    tmp_path, monkeypatch
):
    app = create_phase6_app(tmp_path)
    with app.app_context():
        set_user_tokens()

    service = _AccessibleProjectsService()
    import app.features.automation.sprint_viewer.routes as sprint_routes

    monkeypatch.setattr(sprint_routes, "jira_projects_service", lambda: service)
    monkeypatch.setattr(sprint_routes, "_validate_pat_belongs_to_user", lambda pat: None)
    client = app.test_client()
    login(client)

    invalid = client.post(
        "/api/automation/sprint-viewer/boards",
        json={"project_key": "bad key!"},
    )
    assert invalid.status_code == 400
    assert invalid.get_json()["error"]["code"] == "invalid_project_key"
    assert service.permission_calls == []

    service.has_browse_projects = lambda project_key, pat: False
    unauthorized = client.post(
        "/api/automation/sprint-viewer/boards",
        json={"project_key": "ABC"},
    )
    assert unauthorized.status_code == 403
    assert unauthorized.get_json()["error"]["code"] == "project_not_accessible"
    assert "do not have access" in unauthorized.get_json()["error"]["message"]


def test_board_loading_errors_and_logs_do_not_expose_pat(tmp_path, monkeypatch):
    app = create_phase6_app(tmp_path)
    with app.app_context():
        set_user_tokens()

    class FailingProjectsService:
        def has_browse_projects(self, project_key, pat):
            raise JiraProjectsServiceError("request failed pat_token=jira-pat")

    import app.features.automation.sprint_viewer.routes as sprint_routes

    monkeypatch.setattr(
        sprint_routes, "jira_projects_service", lambda: FailingProjectsService()
    )
    monkeypatch.setattr(sprint_routes, "_validate_pat_belongs_to_user", lambda pat: None)

    client = app.test_client()
    login(client)
    response = client.post(
        "/api/automation/sprint-viewer/boards",
        json={"project_key": "ABC"},
    )

    assert response.status_code == 403
    assert "jira-pat" not in response.get_data(as_text=True)
    assert "pat_token" not in response.get_data(as_text=True)
    for logger in (logging.getLogger(), logging.getLogger("app")):
        for handler in logger.handlers:
            handler.flush()
    log_text = (tmp_path / "test-app.log").read_text(encoding="utf-8")
    assert "jira-pat" not in log_text


def test_project_permission_service_requests_browse_permission():
    class FakeHttpClient:
        def __init__(self):
            self.calls = []

        def get_json(self, path, **kwargs):
            self.calls.append((path, kwargs))
            return {"permissions": {"BROWSE_PROJECTS": {"havePermission": True}}}

    http = FakeHttpClient()
    service = JiraProjectsService("https://jira.example", http_client=http)

    assert service.has_browse_projects("ABC", "secret-pat") is True
    assert http.calls[0][0] == "/rest/api/2/mypermissions"
    assert http.calls[0][1]["params"] == {
        "projectKey": "ABC",
        "permissions": "BROWSE_PROJECTS",
    }


def test_frontend_flow_resets_downstream_state_and_guards_async_requests():
    script = (ROOT / "app/static/js/sprint_viewer.js").read_text(encoding="utf-8")

    assert 'projectKey.addEventListener("input"' in script
    assert 'boardId.addEventListener("change"' in script
    assert 'sprintId.addEventListener("change"' in script
    assert "resetBoardFlow();" in script
    assert "resetSprintFlow();" in script
    assert "resetIssueFlow();" in script
    assert "loadSprints(false);" in script
    assert "if (sprintId.value) fetchIssues();" in script
    assert "new AbortController()" in script
    assert "requestIsCurrent" in script
    assert "if (projectLoading) return;" in script
    assert "if (sprintLoading || !boardsLoaded || !boardId.value) return;" in script
    assert "if (issueLoading || !sprintId.value || !boardId.value) return;" in script


def test_frontend_has_loading_empty_and_error_states_for_each_dependency():
    script = (ROOT / "app/static/js/sprint_viewer.js").read_text(encoding="utf-8")

    for expected in (
        "Validating Jira project",
        "No Jira boards are associated with this project.",
        "Network error while validating the Jira project.",
        "Loading sprints...",
        "No closed sprints were found for this board.",
        "Network error while loading sprints.",
        "Loading issues and sprint metrics...",
        "No issues were found for this sprint.",
        "Network error while fetching sprint issues.",
    ):
        assert expected in script
