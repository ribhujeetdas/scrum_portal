from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config_validation import sqlite_wal_is_safe
from app.core.database import DatabaseInstanceLock
from app.logging_conf import audit_event
from scripts.database_common import application_database, check_connection


def main() -> int:
    app, path = application_database()
    requested = str(app.config.get("SQLITE_JOURNAL_MODE", "DELETE")).upper()
    if requested == "WAL" and not sqlite_wal_is_safe():
        raise RuntimeError(
            f"Refusing WAL with SQLite {sqlite3.sqlite_version}; use DELETE or a patched runtime."
        )
    if requested not in {"DELETE", "WAL"}:
        raise RuntimeError("SQLITE_JOURNAL_MODE must be DELETE or WAL.")

    with DatabaseInstanceLock(path):
        with closing(sqlite3.connect(path, timeout=30)) as connection, connection:
            actual = connection.execute(f"PRAGMA journal_mode={requested}").fetchone()[0]
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(
                f"PRAGMA busy_timeout={int(app.config.get('SQLITE_BUSY_TIMEOUT_MS', 30000))}"
            )
            connection.execute(
                f"PRAGMA synchronous={str(app.config.get('SQLITE_SYNCHRONOUS', 'FULL'))}"
            )
            checks = check_connection(connection)
    if str(actual).upper() != requested:
        raise RuntimeError(f"Unable to set journal mode to {requested}; actual={actual}")
    if not checks["integrity_ok"] or not checks["foreign_key_ok"]:
        raise RuntimeError(f"Database validation failed: {checks}")
    audit_event(
        "database.configuration.updated",
        "SQLite runtime configuration updated",
        resource_type="database",
        resource_id=path.name,
        result="success",
    )
    print(
        f"DATABASE_CONFIG_OK path={path} sqlite={sqlite3.sqlite_version} "
        f"journal_mode={checks['journal_mode']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
