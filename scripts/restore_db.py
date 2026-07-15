from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.logging_conf import audit_event
from scripts.database_common import (
    application_database,
    restore_database,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore a verified Scrum Portal SQLite backup.")
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        parser.error("--confirm is required for restore")

    app, target = application_database()
    backup = args.backup.expanduser().resolve()
    configured = Path(str(app.config.get("DATABASE_BACKUP_DIR", "backups")))
    if not configured.is_absolute():
        configured = Path(app.root_path).parent / configured
    safety_backup = restore_database(target, backup, configured.resolve())
    audit_event(
        "database.backup.restored",
        "SQLite backup restored",
        resource_type="database_backup",
        resource_id=backup.name,
        result="success",
    )
    print(f"RESTORE_OK target={target} safety_backup={safety_backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
