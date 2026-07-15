from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.logging_conf import audit_event
from scripts.database_common import (
    application_database,
    backup_database,
    prune_backups,
)


def main() -> int:
    app, source = application_database()
    configured = Path(str(app.config.get("DATABASE_BACKUP_DIR", "backups")))
    if not configured.is_absolute():
        configured = Path(app.root_path).parent / configured
    backup, metadata = backup_database(source, configured.resolve())
    removed = prune_backups(
        configured.resolve(),
        source.stem,
        int(app.config.get("DATABASE_BACKUP_RETENTION", 14)),
    )
    audit_event(
        "database.backup.created",
        "SQLite backup created",
        resource_type="database_backup",
        resource_id=backup.name,
        result="success",
    )
    print(f"BACKUP_OK path={backup} metadata={metadata} pruned={len(removed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
