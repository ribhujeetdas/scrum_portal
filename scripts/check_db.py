from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.database_common import application_database, check_connection


def main() -> int:
    _app, path = application_database()
    with closing(sqlite3.connect(path, timeout=30)) as connection:
        result = check_connection(connection)
    print(json.dumps(result, indent=2))
    return 0 if result["integrity_ok"] and result["foreign_key_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
