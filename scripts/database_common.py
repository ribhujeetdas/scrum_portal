from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from app import create_app
from app.core.database import DatabaseInstanceLock, sqlite_database_path
from app.extensions import db


def application_database() -> tuple[object, Path]:
    app = create_app()
    with app.app_context():
        path = sqlite_database_path()
        # Release pooled handles before direct SQLite maintenance and Windows replaces.
        db.engine.dispose()
    if path is None:
        raise RuntimeError("This command requires a file-backed SQLite database.")
    return app, path


def check_connection(connection: sqlite3.Connection) -> dict[str, object]:
    integrity_rows = [row[0] for row in connection.execute("PRAGMA integrity_check")]
    foreign_key_rows = list(connection.execute("PRAGMA foreign_key_check"))
    journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    return {
        "integrity_ok": integrity_rows == ["ok"],
        "integrity_results": integrity_rows,
        "foreign_key_ok": not foreign_key_rows,
        "foreign_key_violations": len(foreign_key_rows),
        "journal_mode": journal_mode,
        "sqlite_version": sqlite3.sqlite_version,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_database(source: Path, destination_dir: Path) -> tuple[Path, Path]:
    if not source.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {source}")
    destination_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination = destination_dir / f"{source.stem}-{stamp}.sqlite3"
    if destination.exists():
        raise RuntimeError(f"Backup destination already exists: {destination}")

    with closing(sqlite3.connect(source, timeout=30)) as source_connection:
        with closing(sqlite3.connect(destination)) as destination_connection:
            source_connection.backup(destination_connection)
            checks = check_connection(destination_connection)

    if not checks["integrity_ok"] or not checks["foreign_key_ok"]:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"Backup validation failed: {checks}")

    metadata = {
        "created_at": datetime.now(UTC).isoformat(),
        "source_name": source.name,
        "backup_name": destination.name,
        "sha256": sha256_file(destination),
        "size_bytes": destination.stat().st_size,
        **checks,
    }
    metadata_path = destination.with_suffix(destination.suffix + ".json")
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return destination, metadata_path


def prune_backups(destination_dir: Path, source_stem: str, retention: int) -> list[Path]:
    backups = sorted(
        destination_dir.glob(f"{source_stem}-*.sqlite3"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    removed: list[Path] = []
    for path in backups[retention:]:
        metadata = path.with_suffix(path.suffix + ".json")
        path.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)
        removed.append(path)
    return removed


def verify_backup(backup: Path) -> dict[str, object]:
    backup = backup.expanduser().resolve()
    metadata_path = backup.with_suffix(backup.suffix + ".json")
    if not backup.is_file() or not metadata_path.is_file():
        raise RuntimeError("Backup and its metadata file are required.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if sha256_file(backup) != metadata.get("sha256"):
        raise RuntimeError("Backup checksum does not match metadata.")
    with closing(sqlite3.connect(backup)) as connection:
        checks = check_connection(connection)
    if not checks["integrity_ok"] or not checks["foreign_key_ok"]:
        raise RuntimeError(f"Backup integrity validation failed: {checks}")
    return {**metadata, **checks}


def restore_database(target: Path, backup: Path, backup_dir: Path) -> Path:
    target = target.expanduser().resolve()
    backup = backup.expanduser().resolve()
    verify_backup(backup)
    temporary = target.with_suffix(target.suffix + ".restore.tmp")

    with DatabaseInstanceLock(target):
        safety_backup, _metadata = backup_database(target, backup_dir.resolve())
        try:
            shutil.copy2(backup, temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    with closing(sqlite3.connect(target)) as connection:
        restored = check_connection(connection)
    if not restored["integrity_ok"] or not restored["foreign_key_ok"]:
        raise RuntimeError(f"Restored database failed validation; safety backup={safety_backup}")
    return safety_backup
