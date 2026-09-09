from __future__ import annotations

from datetime import UTC, datetime
import os
import sqlite3

import click
from alembic import command as alembic_command
from flask import Flask, current_app
from sqlalchemy import inspect, text

from .database import enable_and_verify_wal, sqlite_database_path
from .frozen_legacy_schema import EXPECTED_COLUMNS, LEGACY_HEAD, create_legacy_head, legacy_schema_differences
from ..extensions import db


def _schema_state() -> tuple[str, str | None, list[str]]:
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    if not tables:
        return "empty", None, []
    revision = None
    if "alembic_version" in tables:
        revision = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar()
        return "versioned", revision, []
    differences = legacy_schema_differences(db.engine)
    extra_tables = sorted(tables - set(EXPECTED_COLUMNS))
    if extra_tables:
        differences.append("unexpected tables: " + ", ".join(extra_tables))
    return ("legacy_head" if not differences else "unknown"), None, differences


def _apply_setup(adopt_legacy_head: bool, backup_reference: str | None) -> None:
    state, revision, differences = _schema_state()
    # Schema inspection opens a scoped-session read transaction. Release it
    # before Alembic uses its own connection, especially on SQLite/Windows.
    db.session.remove()
    if state == "empty":
        with db.engine.begin() as connection:
            create_legacy_head(connection)
        _record_legacy_head()
    elif state == "legacy_head":
        if not adopt_legacy_head or not backup_reference:
            raise click.ClickException(
                "Unversioned legacy-head schema found. Re-run with --adopt-legacy-head and --backup-reference."
            )
        _record_legacy_head()
    elif state == "unknown":
        raise click.ClickException("Unknown or partial schema: " + "; ".join(differences))
    elif state == "versioned":
        known_revisions = {
            "c3d00bc3ae67", "f8954404f3b1", "44a4a3ce3141", LEGACY_HEAD,
            "a18c9e4d7b01", "b27d5f8a9c02",
        }
        if revision not in known_revisions:
            raise click.ClickException(f"Unknown database revision: {revision}")
    _upgrade_in_committed_transaction()
    enable_and_verify_wal(current_app, db.engine)


def _record_legacy_head() -> None:
    """Record the verified frozen baseline without running historical DDL."""
    with db.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        existing = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).fetchall()
        if existing:
            raise click.ClickException("Refusing to replace an existing migration revision")
        connection.exec_driver_sql(
            "INSERT INTO alembic_version(version_num) VALUES (?)", (LEGACY_HEAD,)
        )


def _upgrade_in_committed_transaction() -> None:
    migration = current_app.extensions["migrate"].migrate
    config = migration.get_config()
    with db.engine.begin() as connection:
        config.attributes["connection"] = connection
        alembic_command.upgrade(config, "heads")


def _backup_database(destination: str) -> None:
    source = sqlite_database_path(current_app)
    if source is None:
        raise click.ClickException("A file-backed SQLite database is required")
    destination = os.path.abspath(destination)
    if destination == source:
        raise click.ClickException("Backup destination must differ from the live database")
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        integrity = destination_connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = destination_connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise click.ClickException("Backup verification failed")
    finally:
        destination_connection.close()
        source_connection.close()


def register_commands(app: Flask) -> None:
    @app.cli.command("setup-db")
    @click.option("--check", "check_only", is_flag=True, help="Inspect schema without changing it.")
    @click.option("--apply", "apply_changes", is_flag=True, help="Apply the safe bootstrap or upgrade.")
    @click.option("--adopt-legacy-head", is_flag=True)
    @click.option("--backup-reference", type=str)
    def setup_db(check_only, apply_changes, adopt_legacy_head, backup_reference):
        if check_only == apply_changes:
            raise click.ClickException("Choose exactly one of --check or --apply")
        state, revision, differences = _schema_state()
        if check_only:
            click.echo(f"state={state} revision={revision or '-'}")
            for difference in differences:
                click.echo(difference)
            return
        _apply_setup(adopt_legacy_head, backup_reference)
        state, revision, _ = _schema_state()
        click.echo(f"Database ready: state={state} revision={revision}")

    @app.cli.command("backup-db")
    @click.option("--destination", required=True, type=click.Path(dir_okay=False))
    def backup_db(destination):
        _backup_database(destination)
        click.echo(f"Verified SQLite backup created at {os.path.abspath(destination)}")

    @app.cli.command("check-db")
    def check_db():
        path = sqlite_database_path(current_app)
        if path is None:
            raise click.ClickException("A file-backed SQLite database is required")
        connection = sqlite3.connect(path)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            connection.close()
        if integrity != "ok" or foreign_keys:
            raise click.ClickException("Database integrity check failed")
        click.echo("Database integrity and foreign keys verified")

    @app.cli.command("worker-status")
    def worker_status():
        from ..features.automation.sprint_viewer.models import WorkerLeader
        row = db.session.get(WorkerLeader, "sprint-worker")
        if not row:
            raise click.ClickException("Sprint worker has not registered")
        click.echo(f"owner={row.owner} epoch={row.epoch} last_heartbeat={row.last_heartbeat.isoformat()}")

    @app.cli.command("rebuild-sprint")
    @click.option("--user-id", required=True, type=int)
    @click.option("--board-id", required=True, type=int)
    @click.option("--sprint-id", required=True, type=int)
    def rebuild_sprint_snapshot(user_id, board_id, sprint_id):
        """Queue an operator-requested snapshot generation; never refresh on ordinary reads."""
        from ..features.automation.sprint_viewer.repository import queue_snapshot_rebuild
        from ..models import User

        user = db.session.get(User, user_id)
        if user is None or not user.is_active:
            raise click.ClickException("Active user not found")
        _scope, snapshot, created = queue_snapshot_rebuild(user, board_id, sprint_id)
        db.session.commit()
        disposition = "queued" if created else "already in progress"
        click.echo(
            f"Snapshot generation {snapshot.generation} {disposition}; "
            f"snapshot_id={snapshot.id}. Existing active generation remains readable."
        )

    @app.cli.command("retry-job")
    @click.option("--job-id", required=True, type=str)
    def retry_job(job_id):
        from ..features.automation.sprint_viewer.models import (
            BackgroundJob, JiraScope, SprintComponent, SprintSnapshot,
        )
        job = db.session.get(BackgroundJob, job_id)
        if job is None:
            raise click.ClickException("Job not found")
        if job.state not in {"failed", "retry_wait"} or job.lease_owner:
            raise click.ClickException("Only an unleased failed or waiting job can be retried")
        scope = db.session.get(JiraScope, job.scope_id)
        if scope is None or scope.revoked_at is not None:
            raise click.ClickException("Job scope is revoked")
        job.state = "queued"
        job.resume_kind = "restart"
        job.attempts = 0
        job.error_code = None
        job.available_at = datetime.now(UTC)
        if job.component_key:
            component = SprintComponent.query.filter_by(
                snapshot_id=job.snapshot_id, component_key=job.component_key
            ).one()
            component.state = "queued"
            component.error_code = None
        snapshot = db.session.get(SprintSnapshot, job.snapshot_id) if job.snapshot_id else None
        if snapshot and snapshot.status == "failed":
            snapshot.status = "processing"
            snapshot.failure_code = None
        db.session.commit()
        click.echo(f"Queued job id={job.id} from a fresh component revision")

    @app.cli.command("purge-staging")
    @click.option("--older-than-days", default=7, show_default=True, type=click.IntRange(1, 3650))
    @click.option("--dry-run", is_flag=True)
    @click.option("--apply", "apply_changes", is_flag=True)
    def purge_staging(older_than_days, dry_run, apply_changes):
        from datetime import timedelta
        from ..features.automation.sprint_viewer.models import SprintComponent, SprintComponentRevision
        if dry_run == apply_changes:
            raise click.ClickException("Choose exactly one of --dry-run or --apply")
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        published_ids = {
            value for (value,) in db.session.query(SprintComponent.published_revision_id)
            .filter(SprintComponent.published_revision_id.is_not(None)).all()
        }
        rows = SprintComponentRevision.query.filter(
            SprintComponentRevision.state.in_(("staging", "failed", "cancelled", "unavailable")),
            SprintComponentRevision.started_at < cutoff,
        ).all()
        removable = [row for row in rows if row.id not in published_ids]
        click.echo(f"eligible_staging_revisions={len(removable)}")
        if apply_changes:
            for row in removable:
                db.session.delete(row)
            db.session.commit()
            click.echo("Unreferenced staging revisions purged")

    @app.cli.command("purge-snapshot")
    @click.option("--snapshot-id", required=True, type=str)
    @click.option("--apply", "apply_changes", is_flag=True)
    def purge_snapshot(snapshot_id, apply_changes):
        from ..features.automation.sprint_viewer.models import SprintSnapshot, SprintSnapshotSeries
        snapshot = db.session.get(SprintSnapshot, snapshot_id)
        if snapshot is None:
            raise click.ClickException("Snapshot not found")
        referenced = SprintSnapshotSeries.query.filter(
            (SprintSnapshotSeries.active_snapshot_id == snapshot.id)
            | (SprintSnapshotSeries.candidate_snapshot_id == snapshot.id)
        ).first()
        if referenced:
            raise click.ClickException("Snapshot is active or candidate and cannot be purged")
        click.echo(f"eligible_snapshot={snapshot.id} status={snapshot.status}")
        if not apply_changes:
            click.echo("Dry run only; pass --apply to delete this explicit snapshot")
            return
        db.session.delete(snapshot)
        db.session.commit()
        click.echo("Snapshot purged")

    def user_option(command):
        command = click.option("--identifier", type=str)(command)
        return click.option("--user-id", type=int)(command)

    def selected_user(user_id, identifier):
        from .admin import find_user
        if (user_id is None) == (not identifier):
            raise click.ClickException("Provide exactly one of --user-id or --identifier")
        return find_user(user_id=user_id, identifier=identifier)

    @app.cli.command("list-users")
    def list_users():
        from ..models import User
        for user in User.query.order_by(User.id).all():
            click.echo(
                f"id={user.id} eid={user.eid} email={user.email} "
                f"active={int(user.active)} deleted={int(user.deleted)}"
            )

    @app.cli.command("disable-user")
    @user_option
    @click.option("--mark-deleted", is_flag=True)
    def disable_user_command(user_id, identifier, mark_deleted):
        from .admin import disable_user
        user = selected_user(user_id, identifier)
        disable_user(user, deleted=mark_deleted)
        db.session.commit()
        click.echo(f"Disabled user id={user.id}; sessions and Jira scopes revoked")

    @app.cli.command("enable-user")
    @user_option
    def enable_user_command(user_id, identifier):
        from .admin import enable_user
        user = selected_user(user_id, identifier)
        enable_user(user)
        db.session.commit()
        click.echo(f"Enabled user id={user.id}; prior sessions remain revoked")

    @app.cli.command("revoke-user-access")
    @user_option
    def revoke_user_access_command(user_id, identifier):
        from .admin import revoke_user_access
        user = selected_user(user_id, identifier)
        revoke_user_access(user)
        db.session.commit()
        click.echo(f"Revoked sessions and Jira scopes for user id={user.id}")

    @app.cli.command("revoke-user-sessions")
    @user_option
    def revoke_user_sessions_command(user_id, identifier):
        from .admin import revoke_sessions_only
        user = selected_user(user_id, identifier)
        revoke_sessions_only(user)
        db.session.commit()
        click.echo(f"Revoked sessions for user id={user.id}")

    @app.cli.command("set-user-password")
    @user_option
    @click.password_option(confirmation_prompt=True)
    def set_user_password_command(user_id, identifier, password):
        from .admin import set_user_password
        user = selected_user(user_id, identifier)
        set_user_password(user, password)
        db.session.commit()
        click.echo(f"Updated password and revoked sessions for user id={user.id}")
