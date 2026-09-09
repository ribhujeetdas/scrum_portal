from __future__ import annotations

from sqlalchemy import Connection, create_engine, inspect


LEGACY_HEAD = "9c2a1f7b6d10"


DDL = (
    """CREATE TABLE users (
        id INTEGER NOT NULL PRIMARY KEY, eid VARCHAR(64) NOT NULL UNIQUE,
        jira_key VARCHAR(64), email VARCHAR(255) NOT NULL UNIQUE,
        display_name VARCHAR(255) NOT NULL, active BOOLEAN NOT NULL,
        deleted BOOLEAN NOT NULL, timezone VARCHAR(64), locale VARCHAR(64),
        password_hash VARCHAR(255) NOT NULL, jira_pat_enc BLOB,
        tableau_pat_name VARCHAR(128), tableau_pat_secret_enc BLOB,
        tableau_site_id VARCHAR(64), tableau_user_id VARCHAR(64),
        tableau_content_url VARCHAR(255), tableau_email VARCHAR(255),
        tableau_eid VARCHAR(128), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    )""",
    """CREATE TABLE user_projects (
        id INTEGER NOT NULL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
        project_key VARCHAR(32) NOT NULL, admin_projects BOOLEAN NOT NULL,
        project_id INTEGER, epic_key VARCHAR(32), created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL, CONSTRAINT uq_user_project_key UNIQUE(user_id, project_key)
    )""",
    "CREATE INDEX ix_user_projects_project_id ON user_projects(project_id)",
    """CREATE TABLE user_boards (
        id INTEGER NOT NULL PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES user_projects(id),
        board_id INTEGER NOT NULL, board_name VARCHAR(255) NOT NULL, board_type VARCHAR(32),
        board_url VARCHAR(1024), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        CONSTRAINT uq_project_board_id UNIQUE(project_id, board_id)
    )""",
    "CREATE INDEX ix_user_boards_board_id ON user_boards(board_id)",
    """CREATE TABLE user_board_sprints (
        id INTEGER NOT NULL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
        board_id INTEGER NOT NULL, sprint_id INTEGER NOT NULL, sprint_name VARCHAR(255) NOT NULL,
        sprint_state VARCHAR(32) NOT NULL, sprint_url VARCHAR(1024), start_date VARCHAR(64),
        end_date VARCHAR(64), complete_date VARCHAR(64), activated_date VARCHAR(64),
        origin_board_id INTEGER, goal TEXT, synced BOOLEAN, auto_start_stop BOOLEAN,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        CONSTRAINT uq_user_board_sprint UNIQUE(user_id, board_id, sprint_id)
    )""",
    """CREATE TABLE user_tableau_custom_views (
        id INTEGER NOT NULL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
        custom_view_id VARCHAR(64) NOT NULL, custom_view_name VARCHAR(255), epic_key VARCHAR(32),
        view_id VARCHAR(64), view_name VARCHAR(255), workbook_id VARCHAR(64), workbook_name VARCHAR(255),
        shared BOOLEAN, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        CONSTRAINT uq_user_custom_view UNIQUE(user_id, custom_view_id)
    )""",
    "CREATE INDEX ix_user_tableau_custom_views_user_updated ON user_tableau_custom_views(user_id, updated_at)",
)


EXPECTED_COLUMNS = {
    "users": {"id", "eid", "jira_key", "email", "display_name", "active", "deleted", "timezone", "locale", "password_hash", "jira_pat_enc", "tableau_pat_name", "tableau_pat_secret_enc", "tableau_site_id", "tableau_user_id", "tableau_content_url", "tableau_email", "tableau_eid", "created_at", "updated_at"},
    "user_projects": {"id", "user_id", "project_key", "admin_projects", "project_id", "epic_key", "created_at", "updated_at"},
    "user_boards": {"id", "project_id", "board_id", "board_name", "board_type", "board_url", "created_at", "updated_at"},
    "user_board_sprints": {"id", "user_id", "board_id", "sprint_id", "sprint_name", "sprint_state", "sprint_url", "start_date", "end_date", "complete_date", "activated_date", "origin_board_id", "goal", "synced", "auto_start_stop", "created_at", "updated_at"},
    "user_tableau_custom_views": {"id", "user_id", "custom_view_id", "custom_view_name", "epic_key", "view_id", "view_name", "workbook_id", "workbook_name", "shared", "created_at", "updated_at"},
}


def create_legacy_head(connection: Connection) -> None:
    for statement in DDL:
        connection.exec_driver_sql(statement)


def _signature(bind) -> dict:
    inspector = inspect(bind)
    output = {}
    for table in EXPECTED_COLUMNS:
        columns = {
            column["name"]: (
                str(column["type"]).upper(),
                bool(column["nullable"]),
                bool(column.get("primary_key")),
            )
            for column in inspector.get_columns(table)
        } if table in inspector.get_table_names() else {}
        output[table] = {
            "columns": columns,
            "unique": sorted(tuple(item["column_names"]) for item in inspector.get_unique_constraints(table)) if columns else [],
            "indexes": sorted((item["name"], tuple(item["column_names"]), bool(item.get("unique"))) for item in inspector.get_indexes(table)) if columns else [],
            "foreign_keys": sorted((tuple(item["constrained_columns"]), item["referred_table"], tuple(item["referred_columns"])) for item in inspector.get_foreign_keys(table)) if columns else [],
        }
    return output


def legacy_schema_differences(bind) -> list[str]:
    """Compare an adoption candidate with a schema built only from frozen DDL."""
    expected_engine = create_engine("sqlite:///:memory:")
    try:
        with expected_engine.begin() as connection:
            create_legacy_head(connection)
        expected = _signature(expected_engine)
        actual = _signature(bind)
    finally:
        expected_engine.dispose()
    differences = []
    for table in EXPECTED_COLUMNS:
        if actual[table] != expected[table]:
            differences.append(f"{table} schema does not exactly match frozen legacy head")
    return differences
