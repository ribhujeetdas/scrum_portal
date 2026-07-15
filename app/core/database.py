from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import BinaryIO

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from flask import Flask
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from app.extensions import db

_write_lock = threading.RLock()


def _is_locked_error(exc: BaseException) -> bool:
    return "database is locked" in str(exc).lower()


def configure_database(app: Flask) -> None:
    """Attach deterministic SQLite connection settings to this app's engine."""
    with app.app_context():
        engine = db.engine
        if engine.dialect.name != "sqlite":
            raise RuntimeError("Only SQLite is supported by this application.")

        busy_timeout = int(app.config.get("SQLITE_BUSY_TIMEOUT_MS", 30000))
        synchronous = str(app.config.get("SQLITE_SYNCHRONOUS", "FULL")).upper()
        if synchronous not in {"OFF", "NORMAL", "FULL", "EXTRA"}:
            raise RuntimeError("Invalid SQLITE_SYNCHRONOUS setting.")

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):
            if not isinstance(dbapi_connection, sqlite3.Connection):
                return
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute(f"PRAGMA busy_timeout={busy_timeout}")
                cursor.execute(f"PRAGMA synchronous={synchronous}")
            finally:
                cursor.close()

        # Ensure the settings also apply to the connection that initialized the engine.
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql(f"PRAGMA busy_timeout={busy_timeout}")
            connection.exec_driver_sql(f"PRAGMA synchronous={synchronous}")


def execute_write[T](
    operation: Callable[[], T],
    *,
    retries: int | None = None,
    backoff_seconds: float | None = None,
) -> T:
    """Run one short transaction with process-local write serialization."""
    from flask import current_app

    retry_total = int(
        retries if retries is not None else current_app.config.get("SQLITE_WRITE_RETRY_TOTAL", 2)
    )
    backoff = float(
        backoff_seconds
        if backoff_seconds is not None
        else current_app.config.get("SQLITE_WRITE_RETRY_BACKOFF_SECONDS", 0.05)
    )

    for attempt in range(retry_total + 1):
        with _write_lock:
            try:
                result = operation()
                db.session.commit()
                return result
            except OperationalError as exc:
                db.session.rollback()
                if not _is_locked_error(exc) or attempt >= retry_total:
                    raise
            except Exception:
                db.session.rollback()
                raise
        time.sleep(backoff * (2**attempt))
    raise RuntimeError("Database write retry loop exited unexpectedly.")


def sqlite_database_path(engine: Engine | None = None) -> Path | None:
    selected = engine or db.engine
    database = selected.url.database
    if not database or database == ":memory:":
        return None
    return Path(database).expanduser().resolve()


def sqlite_health() -> dict[str, object]:
    with db.engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar()
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
        busy_timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()
    path = sqlite_database_path()
    return {
        "sqlite_version": sqlite3.sqlite_version,
        "journal_mode": str(journal_mode or "").lower(),
        "foreign_keys": bool(foreign_keys),
        "busy_timeout_ms": int(busy_timeout or 0),
        "database_path": str(path) if path else ":memory:",
    }


def migration_status() -> dict[str, object]:
    repository_root = Path(__file__).resolve().parents[2]
    alembic_config = AlembicConfig(str(repository_root / "migrations" / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(repository_root / "migrations"))
    expected_heads = tuple(ScriptDirectory.from_config(alembic_config).get_heads())

    with db.engine.connect() as connection:
        table_exists = connection.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).scalar()
        if table_exists:
            current_heads = tuple(
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT version_num FROM alembic_version ORDER BY version_num"
                )
            )
        else:
            current_heads = ()
    return {
        "current_heads": current_heads,
        "expected_heads": expected_heads,
        "current": bool(current_heads) and set(current_heads) == set(expected_heads),
    }


class DatabaseInstanceLock:
    """Cross-platform advisory lock preventing two server processes per DB."""

    def __init__(self, database_path: Path):
        self.path = database_path.with_suffix(database_path.suffix + ".server.lock")
        self._handle: BinaryIO | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(  # type: ignore[attr-defined]
                    handle.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,  # type: ignore[attr-defined]
                )
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise RuntimeError(
                f"Another application process already owns database lock: {self.path}"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(  # type: ignore[attr-defined]
                    self._handle.fileno(),
                    fcntl.LOCK_UN,  # type: ignore[attr-defined]
                )
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        self.release()


@contextlib.contextmanager
def application_database_lock(app: Flask) -> Iterator[DatabaseInstanceLock | None]:
    if not app.config.get("DATABASE_INSTANCE_LOCK", True):
        yield None
        return
    with app.app_context():
        path = sqlite_database_path()
    if path is None:
        yield None
        return
    lock = DatabaseInstanceLock(path)
    lock.acquire()
    logging.getLogger("app.database").info(
        "database instance lock acquired",
        extra={"event": "database.lock.acquired", "database_path": str(path)},
    )
    try:
        yield lock
    finally:
        lock.release()
