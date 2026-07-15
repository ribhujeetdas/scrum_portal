from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet
from flask_migrate import stamp, upgrade
from sqlalchemy import inspect, text

from app import create_app
from app.config import Config
from app.core.database import migration_status, sqlite_health
from app.extensions import db
from app.models import User, UserBoardSprint


class MigrationTestConfig(Config):
    TESTING = True
    APP_ENV = "testing"
    SECRET_KEY = "migration-test-secret"
    WTF_CSRF_ENABLED = False
    FERNET_KEY = Fernet.generate_key().decode("ascii")
    LOG_TO_CONSOLE = False
    DATABASE_INSTANCE_LOCK = False


def test_sprint_datetime_migration_preserves_legacy_values(tmp_path):
    database = tmp_path / "migration.sqlite3"

    class TestConfig(MigrationTestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database.as_posix()}"
        LOG_DIR = str(tmp_path / "logs")

    app = create_app(TestConfig)
    migrations_dir = str(Path(__file__).resolve().parents[1] / "migrations")

    with app.app_context():
        db.create_all()
        user = User(
            eid="E100",
            email="user@example.com",
            display_name="Migration User",
            active=True,
            deleted=False,
            password_hash="unused",
        )
        db.session.add(user)
        db.session.commit()
        db.session.execute(
            text(
                "INSERT INTO user_board_sprints "
                "(user_id, board_id, sprint_id, sprint_name, sprint_state, start_date, "
                "end_date, complete_date, activated_date, created_at, updated_at) "
                "VALUES (:user_id, 10, 20, 'Sprint 20', 'closed', :start_date, "
                ":end_date, :complete_date, :activated_date, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "user_id": user.id,
                "start_date": "2026-01-01T09:00:00.000+0000",
                "end_date": "2026-01-15T17:00:00.000+0000",
                "complete_date": "2026-01-15T18:00:00.000+0000",
                "activated_date": "2026-01-01T09:30:00.000+0000",
            },
        )
        db.session.commit()
        stamp(directory=migrations_dir, revision="9c2a1f7b6d10")
        upgrade(directory=migrations_dir, revision="head")
        db.session.expire_all()

        row = UserBoardSprint.query.one()
        column_types = {
            column["name"]: str(column["type"])
            for column in inspect(db.engine).get_columns("user_board_sprints")
        }

        assert isinstance(row.start_date, datetime)
        assert row.start_date.year == 2026
        assert column_types["start_date"] == "DATETIME"
        assert migration_status()["current"] is True
        assert sqlite_health()["foreign_keys"] is True
