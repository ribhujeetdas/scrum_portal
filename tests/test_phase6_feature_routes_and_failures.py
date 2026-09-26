from __future__ import annotations

import json

from cryptography.fernet import Fernet

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User, UserBoard, UserProject, UserTableauCustomView
from app.services.crypto_service import CryptoService
from app.services.jira_projects_service import JiraProjectsServiceError
from app.services.sprint_viewer_service import SprintViewerServiceError
from app.services.tableau_service import TableauServiceError


FERNET_KEY = Fernet.generate_key().decode("ascii")


class Phase6TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    FERNET_KEY = FERNET_KEY
    LOG_TO_CONSOLE = False
    LOG_FILE = "test-app.log"
    JIRA_BASE_URL = "https://jira.example"
    TABLEAU_BASE_URL = "https://tableau.example"
    JIRA_AUTOMATION_ACTOR_ACCOUNT_ID = "SERVICE_ACTOR"


def create_phase6_app(tmp_path):
    class TestConfig(Phase6TestConfig):
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


def login(client, user_id=1):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def set_user_tokens(jira_pat: bool = True, tableau_pat: bool = False):
    crypto = CryptoService(FERNET_KEY)
    user = db.session.get(User, 1)
    if jira_pat:
        user.jira_pat_enc = crypto.encrypt("jira-pat")
    if tableau_pat:
        user.tableau_pat_name = "pat-name"
        user.tableau_pat_secret_enc = crypto.encrypt("tableau-secret")
        user.tableau_site_id = "site-1"
        user.tableau_user_id = "tableau-user-1"
    db.session.commit()


def add_project(board_ids=(101,), epic_key="ABC"):
    project = UserProject(
        user_id=1,
        project_key="ABC",
        admin_projects=True,
        project_id=12345,
        epic_key=epic_key,
    )
    db.session.add(project)
    db.session.flush()
    for board_id in board_ids:
        db.session.add(
            UserBoard(
                project_id=project.id,
                board_id=board_id,
                board_name=f"Board {board_id}",
                board_type="scrum",
                board_url=f"https://jira.example/boards/{board_id}",
            )
        )
    db.session.commit()
    return project


def add_custom_view():
    db.session.add(
        UserTableauCustomView(
            user_id=1,
            custom_view_id="cv-123",
            custom_view_name="TCI View",
            epic_key="ABC",
        )
    )
    db.session.commit()


def test_ui_pages_render_expected_feature_controls(tmp_path):
    app = create_phase6_app(tmp_path)
    with app.app_context():
        set_user_tokens(tableau_pat=True)
        add_project()
        add_custom_view()

    client = app.test_client()
    login_response = client.get("/auth/login")
    assert login_response.status_code == 200
    assert "Login" in login_response.get_data(as_text=True)

    login(client)

    checks = [
        ("/settings/projects-boards", "projects_boards.js"),
        ("/settings/tableau-custom-views", "tableau_custom_view_settings.js"),
        ("/automation/rule-copier", "rule_copier.js"),
        ("/automation/sprint-viewer", "sprint_viewer.js"),
        ("/reports/tci", "tci_custom_views.js"),
    ]

    for path, expected in checks:
        response = client.get(path)
        assert response.status_code == 200, path
        assert expected in response.get_data(as_text=True), path

    rule_page = client.get("/automation/rule-copier").get_data(as_text=True)
    assert 'id="sourceRule"' in rule_page
    assert 'id="ruleSearch"' not in rule_page
    assert 'id="refreshRulesBtn"' in rule_page


def test_rule_copier_lists_safe_rule_metadata_for_selected_board(tmp_path, monkeypatch):
    app = create_phase6_app(tmp_path)
    with app.app_context():
        set_user_tokens()
        add_project()

    class FakeRuleListService:
        def list_rules_for_project(self, project_identifier, pat):
            assert project_identifier == 12345
            assert pat == "jira-pat"
            return [
                {
                    "id": 20,
                    "name": "Zulu rule",
                    "state": "DISABLED",
                    "components": [{"secret": "not returned"}],
                },
                {"ruleId": "10", "ruleName": "Alpha rule", "status": "ENABLED"},
                {"id": 20, "name": "Zulu rule updated", "state": "ENABLED"},
                {"id": "invalid", "name": "Ignored"},
            ]

    import app.features.automation.rule_copier.routes as rule_routes

    monkeypatch.setattr(rule_routes, "_validate_pat_belongs_to_user", lambda pat: None)
    monkeypatch.setattr(
        rule_routes,
        "_ensure_project_id_for_user_project",
        lambda project_key, board_id, pat: 12345,
    )
    monkeypatch.setattr(rule_routes, "_rule_service", lambda: FakeRuleListService())

    client = app.test_client()
    login(client)
    response = client.post(
        "/api/automation/rule-copier/rules",
        json={"project_key": "abc", "board_id": 101},
    )
    data = response.get_json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["count"] == 2
    assert data["rules"] == [
        {"id": 10, "name": "Alpha rule", "state": "ENABLED"},
        {"id": 20, "name": "Zulu rule updated", "state": "ENABLED"},
    ]
    assert "components" not in data["rules"][0]


def test_rule_copier_fetch_does_not_expose_raw_rule_secrets(tmp_path, monkeypatch):
    app = create_phase6_app(tmp_path)
    with app.app_context():
        set_user_tokens()
        add_project()

    class FakeSensitiveRuleService:
        def get_rule_detail(self, project_identifier, rule_id, pat):
            return {
                "id": rule_id,
                "name": "Sensitive outbound rule",
                "state": "ENABLED",
                "components": [
                    {
                        "headers": [
                            {
                                "name": "Authorization",
                                "value": "Bearer must-never-reach-browser",
                            }
                        ]
                    }
                ],
            }

    import app.features.automation.rule_copier.routes as rule_routes

    monkeypatch.setattr(rule_routes, "_validate_pat_belongs_to_user", lambda pat: None)
    monkeypatch.setattr(
        rule_routes,
        "_ensure_project_id_for_user_project",
        lambda project_key, board_id, pat: 12345,
    )
    monkeypatch.setattr(rule_routes, "_rule_service", lambda: FakeSensitiveRuleService())

    client = app.test_client()
    login(client)
    response = client.post(
        "/api/automation/rule-copier/fetch",
        json={"project_key": "ABC", "board_id": 101, "rule_id": 555},
    )
    data = response.get_json()
    serialized = json.dumps(data)

    assert response.status_code == 200
    assert "rule_json" not in data
    assert "must-never-reach-browser" not in serialized
    assert data["sanitization"] == {
        "redacted_count": 1,
        "redacted_header_names": ["Authorization"],
        "redacted_field_names": [],
        "source_secret_names": [],
    }


def test_automation_pages_redirect_to_projects_when_no_projects_exist(tmp_path):
    app = create_phase6_app(tmp_path)
    client = app.test_client()
    login(client)

    for path in ("/automation/rule-copier", "/automation/sprint-viewer"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302
        assert "/settings/projects-boards" in response.headers["Location"]


def test_canonical_api_validation_errors_include_request_id(tmp_path):
    app = create_phase6_app(tmp_path)
    client = app.test_client()
    login(client)

    response = client.post(
        "/api/automation/rule-copier/fetch",
        json={"project_key": "ABC", "board_id": "not-a-board", "rule_id": "123"},
        headers={"X-Request-ID": "phase6-api-123"},
    )
    data = response.get_json()

    assert response.status_code == 400
    assert response.headers["X-Request-ID"] == "phase6-api-123"
    assert data["ok"] is False
    assert data["request_id"] == "phase6-api-123"
    assert data["error"]["message"] == "Board ID must be a positive integer."


def test_canonical_sprint_api_rejects_board_outside_user_projects(tmp_path):
    app = create_phase6_app(tmp_path)
    with app.app_context():
        set_user_tokens()
        add_project(board_ids=(101,))

    client = app.test_client()
    login(client)

    response = client.post(
        "/api/automation/sprint-viewer/issues",
        json={"board_id": 999, "sprint_id": 202},
    )
    data = response.get_json()

    assert response.status_code == 403
    assert data["ok"] is False
    assert "Selected board does not belong" in data["error"]["message"]


def test_projects_route_handles_mocked_jira_project_failure(tmp_path, monkeypatch):
    app = create_phase6_app(tmp_path)
    with app.app_context():
        set_user_tokens()

    class FailingProjectsService:
        def __init__(self, base_url):
            self.base_url = base_url

        def has_administer_projects(self, project_key, pat):
            raise JiraProjectsServiceError("Jira permission API failed")

    import app.features.settings.projects_boards.routes as project_routes

    monkeypatch.setattr(project_routes, "JiraProjectsService", FailingProjectsService)

    client = app.test_client()
    login(client)
    response = client.post(
        "/settings/projects-boards",
        data={"project_key": "ABC", "validate_and_add": "Validate & Add Project"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Unable to validate Jira project permissions." in html
    assert "Jira permission API failed" not in html
    assert "portal-toast" in html


def test_tableau_custom_view_route_handles_mocked_tableau_failure(
    tmp_path, monkeypatch
):
    app = create_phase6_app(tmp_path)
    with app.app_context():
        set_user_tokens(tableau_pat=True)
        add_project()

    class FailingTableauService:
        def fetch_custom_view_details_by_id(self, **kwargs):
            raise TableauServiceError("Tableau custom view lookup failed")

    import app.features.settings.tableau_custom_views.routes as tableau_routes

    monkeypatch.setattr(tableau_routes, "tableau_service", lambda: FailingTableauService())

    client = app.test_client()
    login(client)
    response = client.post(
        "/settings/tableau-custom-views",
        data={
            "epic_key": "ABC",
            "tableau_custom_view_id": "cv-123",
            "save_tableau_custom_view": "Save Custom View",
        },
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Unable to validate the Tableau custom view." in html
    assert "Tableau custom view lookup failed" not in html
    assert "portal-toast" in html


def test_tci_preview_route_handles_mocked_tableau_csv_failure(tmp_path, monkeypatch):
    app = create_phase6_app(tmp_path)
    with app.app_context():
        set_user_tokens(tableau_pat=True)
        add_project()
        add_custom_view()

    class FailingTableauService:
        def sign_in_with_pat(self, pat_name, pat_secret):
            return {"token": "token"}

        def query_custom_view_data_csv(self, **kwargs):
            raise TableauServiceError("Tableau CSV export failed")

        def sign_out(self, token):
            return None

    import app.features.reports.tci.routes as tci_routes

    monkeypatch.setattr(tci_routes, "tableau_service", lambda: FailingTableauService())

    client = app.test_client()
    login(client)
    response = client.post(
        "/reports/tci",
        data={"custom_view_id": "cv-123", "preview_data": "Preview Data"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Unable to load TCI report data." in html
    assert "Tableau CSV export failed" not in html
    assert "portal-toast" in html


def test_canonical_sprint_sprints_api_handles_mocked_jira_failure(
    tmp_path, monkeypatch
):
    app = create_phase6_app(tmp_path)
    with app.app_context():
        set_user_tokens()
        add_project(board_ids=(101,))

    class FailingSprintService:
        def fetch_closed_sprints_for_board(self, board_id, pat):
            raise SprintViewerServiceError("Jira sprint API failed")

    import app.features.automation.sprint_viewer.routes as sprint_routes

    monkeypatch.setattr(sprint_routes, "_get_user_pat", lambda: "pat")
    monkeypatch.setattr(sprint_routes, "_validate_pat_belongs_to_user", lambda pat: None)
    monkeypatch.setattr(sprint_routes, "_sprint_service", lambda: FailingSprintService())

    client = app.test_client()
    login(client)
    response = client.post(
        "/api/automation/sprint-viewer/sprints",
        json={"project_key": "ABC", "board_id": 101, "refresh": False},
    )
    data = response.get_json()

    assert response.status_code == 400
    assert data["ok"] is False
    assert data["error"]["message"] == (
        "Unable to load sprints. Please try again. "
        "If it continues, contact support with the request ID."
    )
