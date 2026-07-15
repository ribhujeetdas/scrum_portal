from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from flask_migrate import stamp, upgrade
from sqlalchemy import inspect

from app.core.database import DatabaseInstanceLock, migration_status
from app.extensions import db
from app.logging_conf import audit_event
from scripts.database_common import application_database, backup_database

_APPLICATION_TABLES = {
    "users",
    "user_projects",
    "user_boards",
    "user_board_sprints",
    "user_tableau_custom_views",
}


def main() -> int:
    app, path = application_database()
    migrations_dir = REPO_ROOT / "migrations"
    configured_backup_dir = Path(str(app.config.get("DATABASE_BACKUP_DIR", "backups")))
    if not configured_backup_dir.is_absolute():
        configured_backup_dir = REPO_ROOT / configured_backup_dir

    with DatabaseInstanceLock(path), app.app_context():
        existing_tables = set(inspect(db.engine).get_table_names())
        application_tables = existing_tables & _APPLICATION_TABLES
        safety_backup = None

        if application_tables and application_tables != _APPLICATION_TABLES:
            missing = sorted(_APPLICATION_TABLES - application_tables)
            raise RuntimeError(
                "Database has a partial application schema; refusing automatic migration. "
                f"Missing tables: {missing}"
            )

        if not application_tables:
            db.create_all()
            stamp(directory=str(migrations_dir), revision="head")
            action = "initialized"
        else:
            safety_backup, _metadata = backup_database(path, configured_backup_dir.resolve())
            upgrade(directory=str(migrations_dir), revision="head")
            action = "upgraded"

        status = migration_status()
        if not status["current"]:
            raise RuntimeError(f"Migration did not reach repository head: {status}")

    audit_event(
        "database.migration.completed",
        "SQLite schema migration completed",
        resource_type="database",
        resource_id=path.name,
        result="success",
    )
    print(
        f"MIGRATION_OK action={action} path={path} "
        f"safety_backup={safety_backup or '-'} head={status['current_heads']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
