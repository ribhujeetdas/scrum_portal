from __future__ import annotations

from cryptography.fernet import Fernet

from app import create_app
from app.config import Config
from app.core.config_validation import collect_config_warnings


class ConfigValidationTestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    FERNET_KEY = Fernet.generate_key().decode("ascii")
    LOG_TO_CONSOLE = False
    LOG_FILE = "test-app.log"


def test_config_validation_warns_for_missing_required_integrations(tmp_path):
    class TestConfig(ConfigValidationTestConfig):
        LOG_DIR = str(tmp_path)
        JIRA_BASE_URL = ""
        TABLEAU_BASE_URL = ""

    app = create_app(TestConfig)

    warnings = collect_config_warnings(app)

    assert "JIRA_BASE_URL is missing." in warnings
    assert "TABLEAU_BASE_URL is missing." in warnings


def test_config_validation_accepts_complete_required_config(tmp_path):
    class TestConfig(ConfigValidationTestConfig):
        LOG_DIR = str(tmp_path)
        JIRA_BASE_URL = "https://jira.example"
        TABLEAU_BASE_URL = "https://tableau.example"

    app = create_app(TestConfig)

    assert collect_config_warnings(app) == []
