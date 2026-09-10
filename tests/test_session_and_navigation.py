from __future__ import annotations

import re

from cryptography.fernet import Fernet

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User, UserProject


class SessionNavTestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    FERNET_KEY = Fernet.generate_key().decode("ascii")
    LOG_TO_CONSOLE = False
    LOG_FILE = "test-app.log"
    SESSION_TIMEOUT_MINUTES = 10
    SESSION_WARNING_THRESHOLD_RATIO = 0.8


def create_test_app(tmp_path):
    class TestConfig(SessionNavTestConfig):
        LOG_DIR = str(tmp_path)

    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
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
        db.session.commit()
    return app


def create_csrf_test_app(tmp_path):
    class TestConfig(SessionNavTestConfig):
        LOG_DIR = str(tmp_path)
        WTF_CSRF_ENABLED = True

    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        user = User(
            eid="E123",
            jira_key="JIRAUSER1",
            email="user@wellsfargo.com",
            display_name="Test User",
            active=True,
            deleted=False,
            password_hash="not-used",
        )
        user.set_password("Password123")
        db.session.add(user)
        db.session.commit()
    return app


def create_uninitialized_test_app(tmp_path):
    class TestConfig(SessionNavTestConfig):
        TESTING = True
        LOG_DIR = str(tmp_path)
        RATE_LIMITS_ENABLED = True

    return create_app(TestConfig)


def login_test_user(client, user_id=1):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def test_anonymous_error_page_does_not_render_authenticated_sidebar(tmp_path):
    app = create_test_app(tmp_path)

    response = app.test_client().get("/route-that-does-not-exist")
    html = response.get_data(as_text=True)

    assert response.status_code == 404
    assert '<nav class="sidebar' not in html
    assert "Settings" not in html


def test_signup_reports_uninitialized_database_without_internal_error(tmp_path):
    app = create_uninitialized_test_app(tmp_path)

    response = app.test_client().post("/auth/signup", data={})

    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "DATABASE_SETUP_REQUIRED"


def test_session_status_initializes_configured_expiry(tmp_path):
    app = create_test_app(tmp_path)
    client = app.test_client()
    login_test_user(client)

    response = client.get("/session/status")
    data = response.get_json()

    assert response.status_code == 200
    assert data["authenticated"] is True
    assert data["timeout_seconds"] == 600
    assert data["warning_after_seconds"] == 480
    assert data["warning_remaining_seconds"] == 120
    assert 590 <= data["remaining_seconds"] <= 600


def test_session_extend_adds_full_timeout_to_existing_expiry(tmp_path):
    app = create_test_app(tmp_path)
    client = app.test_client()
    login_test_user(client)

    first = client.get("/session/status").get_json()
    original_expires_at = first["expires_at"]

    response = client.post("/session/extend")
    data = response.get_json()

    assert response.status_code == 200
    assert data["ok"] is True
    assert data["expires_at"] == original_expires_at + 600
    assert 1190 <= data["remaining_seconds"] <= 1200


def test_rule_copier_redirects_to_projects_when_no_project_keys(tmp_path):
    app = create_test_app(tmp_path)
    client = app.test_client()
    login_test_user(client)

    response = client.get("/automation/rule-copier", follow_redirects=False)

    assert response.status_code == 302
    assert "/settings/projects-boards" in response.headers["Location"]


def test_sprint_viewer_redirects_to_projects_when_no_project_keys(tmp_path):
    app = create_test_app(tmp_path)
    client = app.test_client()
    login_test_user(client)

    response = client.get("/automation/sprint-viewer", follow_redirects=False)

    assert response.status_code == 302
    assert "/settings/projects-boards" in response.headers["Location"]


def test_automation_pages_load_when_project_key_exists(tmp_path):
    app = create_test_app(tmp_path)
    with app.app_context():
        db.session.add(
            UserProject(user_id=1, project_key="ABC", admin_projects=True)
        )
        db.session.commit()

    client = app.test_client()
    login_test_user(client)

    assert client.get("/automation/rule-copier").status_code == 200
    assert client.get("/automation/sprint-viewer").status_code == 200


def test_login_rejects_stale_csrf_then_accepts_a_fresh_form(tmp_path):
    app = create_csrf_test_app(tmp_path)
    client = app.test_client()

    login_page = client.get("/auth/login").get_data(as_text=True)
    token = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', login_page).group(1)

    with client.session_transaction() as sess:
        sess.clear()

    response = client.post(
        "/auth/login",
        data={
            "csrf_token": token,
            "identifier": "user@wellsfargo.com",
            "password": "Password123",
            "submit": "Login",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.headers.get("Location") is None

    fresh_page = client.get("/auth/login").get_data(as_text=True)
    fresh_token = re.search(
        r'name="csrf_token" type="hidden" value="([^"]+)"', fresh_page
    ).group(1)
    fresh_response = client.post(
        "/auth/login",
        data={
            "csrf_token": fresh_token,
            "identifier": "user@wellsfargo.com",
            "password": "Password123",
            "submit": "Login",
        },
        follow_redirects=False,
    )

    assert fresh_response.status_code == 302
    assert fresh_response.headers["Location"].endswith("/dashboard")
