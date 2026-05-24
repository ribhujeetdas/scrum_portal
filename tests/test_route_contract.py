from __future__ import annotations

from cryptography.fernet import Fernet

from app import create_app
from app.config import Config


class RouteContractTestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    FERNET_KEY = Fernet.generate_key().decode("ascii")
    LOG_TO_CONSOLE = False
    LOG_FILE = "test-app.log"


def create_route_app(tmp_path):
    class TestConfig(RouteContractTestConfig):
        LOG_DIR = str(tmp_path)

    return create_app(TestConfig)


def route_rules(app):
    return {rule.rule for rule in app.url_map.iter_rules()}


def test_canonical_user_facing_routes_are_registered(tmp_path):
    app = create_route_app(tmp_path)

    assert {
        "/dashboard",
        "/auth/login",
        "/auth/signup",
        "/settings/integrations",
        "/settings/projects-boards",
        "/settings/tableau-custom-views",
        "/reports/tci",
    }.issubset(route_rules(app))


def test_canonical_api_routes_are_registered(tmp_path):
    app = create_route_app(tmp_path)

    assert {
        "/api/automation/rule-copier/fetch",
        "/api/automation/rule-copier/copy",
        "/api/automation/sprint-viewer/sprints",
        "/api/automation/sprint-viewer/issues",
        "/api/automation/sprint-viewer/metrics",
        "/api/reports/tci/link-details",
        "/api/session/status",
        "/api/session/extend",
        "/api/client-log",
    }.issubset(route_rules(app))


def test_existing_routes_remain_registered_for_backwards_compatibility(tmp_path):
    app = create_route_app(tmp_path)

    assert {
        "/home",
        "/login",
        "/config/integrations",
        "/config/projects",
        "/config/custom-views",
        "/tableau/custom-views",
    }.issubset(route_rules(app))


def test_auth_login_canonical_route_renders_login_page(tmp_path):
    app = create_route_app(tmp_path)

    response = app.test_client().get("/auth/login")

    assert response.status_code == 200
    assert b"Login" in response.data
