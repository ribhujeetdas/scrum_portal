from __future__ import annotations

import os
import sqlite3
from urllib.parse import unquote

from flask import Flask
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool


@event.listens_for(Engine, "connect")
def configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=FULL")
    finally:
        cursor.close()


def configure_database(app: Flask) -> None:
    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    if uri.startswith("sqlite:///") and uri != "sqlite:///:memory:":
        options = dict(app.config.get("SQLALCHEMY_ENGINE_OPTIONS") or {})
        options.setdefault("poolclass", NullPool)
        connect_args = dict(options.get("connect_args") or {})
        connect_args.setdefault(
            "timeout", max(0.1, int(app.config.get("SQLITE_BUSY_TIMEOUT_MS", 5000)) / 1000)
        )
        options["connect_args"] = connect_args
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = options


def sqlite_database_path(app: Flask) -> str | None:
    uri = str(app.config.get("SQLALCHEMY_DATABASE_URI") or "")
    if not uri.startswith("sqlite:///") or uri == "sqlite:///:memory:":
        return None
    value = unquote(uri.removeprefix("sqlite:///"))
    if os.path.isabs(value):
        return os.path.abspath(value)
    return os.path.abspath(os.path.join(app.instance_path, value))


def enable_and_verify_wal(app: Flask, engine: Engine) -> str:
    path = sqlite_database_path(app)
    if path is None:
        return "memory"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with engine.connect() as connection:
        mode = str(connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar()).lower()
        if mode != "wal":
            raise RuntimeError("SQLite WAL mode could not be enabled")
        fk = int(connection.exec_driver_sql("PRAGMA foreign_keys").scalar())
        if fk != 1:
            raise RuntimeError("SQLite foreign key enforcement is disabled")
    return mode
