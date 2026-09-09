from __future__ import annotations

import sqlite3
import threading

from cryptography.fernet import Fernet
import pytest

from app import create_app
from app.config import Config
from app.core.security import invalidate_user_access
from app.extensions import db
from app.features.automation.sprint_viewer.models import (
    BackgroundJob,
    JiraRequestSlot,
    JiraScope,
    SprintSnapshotSeries,
)
from app.features.automation.sprint_viewer.jobs import acquire_leadership, claim_job
from app.features.automation.sprint_viewer.repository import get_or_create_snapshot, queue_snapshot_rebuild
from app.integrations.jira.pagination import JiraPaginationError, collect_offset_pages
from app.models import User, UserBoard, UserBoardSprint, UserProject
from app.services.sprint_viewer_service import SprintViewerService


def _issue(issue_id, assignee, *, histories=None, comments=None):
    return {
        "id": str(issue_id),
        "key": f"ABC-{issue_id}",
        "fields": {
            "summary": "Example",
            "customfield_10106": 3,
            "issuetype": {"name": "Story", "subtask": False},
            "status": {"name": "Done"},
            "assignee": assignee,
            "comment": {"total": len(comments or []), "comments": comments or []},
        },
        "changelog": {"histories": histories or []},
    }


def test_server_capped_pagination_uses_actual_page_length_and_deduplicates():
    calls = []
    pages = {
        0: {"startAt": 0, "maxResults": 2, "total": 3, "isLast": False,
            "issues": [{"id": "1", "points": 4}, {"id": "2", "points": 2}]},
        2: {"startAt": 2, "maxResults": 2, "total": 3, "isLast": True,
            "issues": [{"id": "3", "points": 3}]},
    }

    def fetch(start, requested):
        calls.append((start, requested))
        return pages[start]

    result = collect_offset_pages(
        fetch,
        collection_key="issues",
        requested_page_size=200,
        identity=lambda item: item["id"],
    )

    assert calls == [(0, 200), (2, 200)]
    assert [row["id"] for row in result] == ["1", "2", "3"]
    assert sum(row["points"] for row in result) == 9


def test_identical_duplicate_across_pages_is_deduplicated_without_truncation():
    pages = {
        0: {"startAt": 0, "total": 3, "isLast": False, "issues": [{"id": "1"}, {"id": "2"}]},
        2: {"startAt": 2, "total": 3, "isLast": True, "issues": [{"id": "2"}]},
    }
    result = collect_offset_pages(
        lambda start, _size: pages[start],
        collection_key="issues",
        requested_page_size=50,
        identity=lambda item: item["id"],
    )
    assert [row["id"] for row in result] == ["1", "2"]


def test_empty_nonfinal_page_fails_instead_of_publishing_partial_data():
    with pytest.raises(JiraPaginationError, match="empty non-final"):
        collect_offset_pages(
            lambda _start, _size: {
                "startAt": 0, "total": 3, "isLast": False, "issues": []
            },
            collection_key="issues",
            requested_page_size=50,
            identity=lambda item: item["id"],
        )


def test_complete_empty_changelog_is_not_reported_as_missing_history():
    issue = _issue("1", {"key": "KEY1", "name": "E1"})
    issue["changelog"] = {"total": 0, "histories": []}
    extracted = SprintViewerService.extract_issue_fields(
        issue, "2026-01-01T00:00:00.000+0000"
    )
    assert extracted["historical_fallback"] is False


def test_jira_username_and_historical_key_form_one_principal_group():
    cutoff = "2026-01-01T00:00:00.000+0000"
    issues = [
        _issue("1", {"key": "JIRAUSER123", "name": "E123", "displayName": "A User"}),
        _issue(
            "2",
            {"key": "OTHER", "name": "E999", "displayName": "Other"},
            histories=[{
                "created": "2026-01-02T00:00:00.000+0000",
                "items": [{
                    "field": "assignee",
                    "from": "JIRAUSER123",
                    "fromString": "E123",
                    "to": "OTHER",
                    "toString": "E999",
                }],
            }],
        ),
    ]
    resolver = SprintViewerService.build_identity_resolver(issues)
    extracted = [SprintViewerService.extract_issue_fields(row, cutoff, resolver) for row in issues]
    groups = SprintViewerService("https://jira.example").group_issues_by_assignee(extracted)

    assert len(groups) == 1
    assert groups[0]["principal_id"] == "key:JIRAUSER123"
    assert groups[0]["issue_count"] == 2


def test_same_display_name_with_distinct_keys_stays_separate():
    issues = [
        _issue("1", {"key": "KEY1", "name": "E1", "displayName": "Same Name"}),
        _issue("2", {"key": "KEY2", "name": "E2", "displayName": "Same Name"}),
    ]
    resolver = SprintViewerService.build_identity_resolver(issues)
    extracted = [SprintViewerService.extract_issue_fields(row, resolver=resolver) for row in issues]
    groups = SprintViewerService("https://jira.example").group_issues_by_assignee(extracted)
    assert {group["principal_id"] for group in groups} == {"key:KEY1", "key:KEY2"}


def test_comment_key_matches_assignee_username_through_principal_identity():
    comment = {
        "id": "10",
        "author": {"key": "KEY1"},
        "created": "2025-12-31T00:00:00.000+0000",
    }
    issues = [_issue(
        "1",
        {"key": "KEY1", "name": "E1", "displayName": "A User"},
        comments=[comment],
    )]
    resolver = SprintViewerService.build_identity_resolver(issues)
    extracted = [SprintViewerService.extract_issue_fields(issues[0], resolver=resolver)]
    SprintViewerService.apply_relevant_comment_counts(extracted)
    assert extracted[0]["relevant_comment_count"] == 1


def test_empty_database_safe_bootstrap_is_repeatable_and_backup_is_valid(tmp_path):
    database_path = tmp_path / "portal.db"
    backup_path = tmp_path / "backup" / "portal.db"

    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        WTF_CSRF_ENABLED = False
        FERNET_KEY = Fernet.generate_key().decode("ascii")
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path.as_posix()}"
        LOG_TO_CONSOLE = False
        LOG_LEVEL = "WARNING"
        LOG_DIR = str(tmp_path / "logs")

    app = create_app(TestConfig)
    runner = app.test_cli_runner()
    first = runner.invoke(args=["setup-db", "--apply"])
    assert first.exit_code == 0, first.output
    second = runner.invoke(args=["setup-db", "--apply"])
    assert second.exit_code == 0, second.output
    backup = runner.invoke(args=["backup-db", "--destination", str(backup_path)])
    assert backup.exit_code == 0, backup.output

    connection = sqlite3.connect(backup_path)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "b27d5f8a9c02"
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert {"sprint_snapshots", "background_jobs", "auth_sessions"} <= tables
    finally:
        connection.close()


def test_snapshot_miss_is_deduplicated_and_user_revocation_cancels_jobs(tmp_path):
    class SnapshotConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        WTF_CSRF_ENABLED = False
        FERNET_KEY = Fernet.generate_key().decode("ascii")
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        JIRA_BASE_URL = "https://jira.example"
        JIRA_SOURCE_ID = "test-jira"
        LOG_TO_CONSOLE = False
        LOG_LEVEL = "WARNING"
        LOG_DIR = str(tmp_path / "logs")

    app = create_app(SnapshotConfig)
    with app.app_context():
        db.create_all()
        user = User(
            eid="E123",
            jira_key="KEY123",
            email="user@example.com",
            display_name="User",
            password_hash="hash",
            jira_pat_enc=b"encrypted-placeholder",
        )
        db.session.add(user)
        db.session.flush()
        project = UserProject(
            user_id=user.id, project_key="ABC", admin_projects=True, project_id=100
        )
        db.session.add(project)
        db.session.flush()
        db.session.add(UserBoard(
            project_id=project.id,
            board_id=101,
            board_name="Board",
            board_type="scrum",
        ))
        db.session.add(UserBoardSprint(
            user_id=user.id,
            board_id=101,
            sprint_id=202,
            sprint_name="Sprint",
            sprint_state="closed",
        ))
        db.session.commit()

        first_scope, first_snapshot, created = get_or_create_snapshot(user, 101, 202)
        db.session.commit()
        second_scope, second_snapshot, created_again = get_or_create_snapshot(user, 101, 202)
        db.session.commit()

        assert created is True
        assert created_again is False
        assert first_scope.id == second_scope.id
        assert first_snapshot.id == second_snapshot.id
        assert BackgroundJob.query.filter_by(job_type="sprint_core").count() == 1
        assert JiraRequestSlot.query.filter_by(source_id=first_scope.source_id).count() == 4

        series = SprintSnapshotSeries.query.one()
        first_snapshot.status = "ready"
        BackgroundJob.query.filter_by(snapshot_id=first_snapshot.id).one().state = "succeeded"
        series.active_snapshot_id = first_snapshot.id
        series.candidate_snapshot_id = None
        db.session.commit()
        _scope, replacement, rebuild_created = queue_snapshot_rebuild(user, 101, 202)
        db.session.commit()
        _scope, same_replacement, duplicate_rebuild = queue_snapshot_rebuild(user, 101, 202)
        db.session.commit()
        assert rebuild_created is True
        assert duplicate_rebuild is False
        assert replacement.generation == 2
        assert same_replacement.id == replacement.id
        assert series.active_snapshot_id == first_snapshot.id

        invalidate_user_access(user, credentials_changed=True)
        db.session.commit()
        assert JiraScope.query.filter_by(id=first_scope.id).one().revoked_at is not None
        assert BackgroundJob.query.filter_by(state="cancelled").count() == 1


def test_unauthenticated_api_uses_json_401(tmp_path):
    class ApiConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        WTF_CSRF_ENABLED = False
        FERNET_KEY = Fernet.generate_key().decode("ascii")
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        JIRA_BASE_URL = "https://jira.example"
        LOG_TO_CONSOLE = False
        LOG_LEVEL = "WARNING"
        LOG_DIR = str(tmp_path / "api-logs")

    app = create_app(ApiConfig)
    with app.app_context():
        db.create_all()
    response = app.test_client().get("/api/automation/sprint-viewer/snapshots/missing/status")
    assert response.status_code == 401
    assert response.is_json
    assert response.get_json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_file_backed_sqlite_claim_fence_allows_one_consumer(tmp_path):
    database_path = tmp_path / "claim.db"

    class ClaimConfig(Config):
        TESTING = True
        SECRET_KEY = "test-secret"
        WTF_CSRF_ENABLED = False
        FERNET_KEY = Fernet.generate_key().decode("ascii")
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path.as_posix()}"
        JIRA_BASE_URL = "https://jira.example"
        JIRA_SOURCE_ID = "claim-jira"
        ENABLE_SQLITE_WAL = True
        LOG_TO_CONSOLE = False
        LOG_LEVEL = "WARNING"
        LOG_DIR = str(tmp_path / "claim-logs")

    app = create_app(ClaimConfig)
    with app.app_context():
        db.create_all()
        user = User(eid="E1", email="one@example.com", display_name="One", password_hash="x", jira_pat_enc=b"x")
        db.session.add(user); db.session.flush()
        project = UserProject(user_id=user.id, project_key="ABC", admin_projects=True)
        db.session.add(project); db.session.flush()
        db.session.add(UserBoard(project_id=project.id, board_id=1, board_name="Board"))
        db.session.add(UserBoardSprint(user_id=user.id, board_id=1, sprint_id=2, sprint_name="Sprint", sprint_state="closed"))
        db.session.commit()
        get_or_create_snapshot(user, 1, 2)
        db.session.commit()
        epoch = acquire_leadership("worker")

    barrier = threading.Barrier(2)
    claimed: list[str | None] = []

    def consumer():
        with app.app_context():
            barrier.wait()
            job = claim_job("worker", epoch, "core")
            claimed.append(job.id if job else None)
            db.session.remove()

    threads = [threading.Thread(target=consumer) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert sum(value is not None for value in claimed) == 1
