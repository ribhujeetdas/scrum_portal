from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import create_app
from app.core.config_validation import (
    ConfigurationError,
    collect_config_errors,
    collect_config_warnings,
)
from app.core.database import migration_status, sqlite_health


def main() -> int:
    try:
        app = create_app()
    except ConfigurationError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "app_env": "production",
                    "config_errors": list(exc.errors),
                    "database": "not_checked",
                },
                indent=2,
            )
        )
        return 1
    with app.app_context():
        database = sqlite_health()
        migrations = migration_status()

    log_dir = Path(str(app.config.get("LOG_DIR", "logs")))
    if not log_dir.is_absolute():
        log_dir = Path(app.root_path).parent / log_dir
    log_dir = log_dir.resolve()
    disk = shutil.disk_usage(log_dir)

    report = {
        "ok": not collect_config_errors(app)
        and bool(database["foreign_keys"])
        and bool(migrations["current"]),
        "application_version": app.config.get("APPLICATION_VERSION", "dev"),
        "app_env": app.config.get("APP_ENV"),
        "config_errors": collect_config_errors(app),
        "config_warnings": collect_config_warnings(app),
        "database": database,
        "migrations": migrations,
        "log_storage": {
            "writable": os.access(log_dir, os.W_OK),
            "free_mb": int(disk.free / (1024 * 1024)),
        },
    }
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
