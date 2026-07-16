from __future__ import annotations

import threading
import time
from datetime import timedelta

from cryptography.fernet import Fernet

from app import create_app
from app.config import Config
from app.core.http_client import ExternalServiceError
from app.extensions import db
from app.features.automation.sprint_viewer.metric_jobs import (
    METRICS_VERSION,
    SprintMetricCoordinator,
    _initial_progress,
)
from app.models import User, UserBoard, UserProject, UserSprintMetricRun, utc_now
from app.services.crypto_service import CryptoService
from app.services.sprint_viewer_service import SprintViewerService, SprintViewerServiceError


class MetricJobTestConfig(Config):
    TESTING = True
    APP_ENV = "testing"
    SECRET_KEY = "metric-job-test-secret"
    WTF_CSRF_ENABLED = False
    DATABASE_INSTANCE_LOCK = False
    FERNET_KEY = Fernet.generate_key().decode("ascii")
    JIRA_BASE_URL = "https://jira.example"
    LOG_TO_CONSOLE = False
    SPRINT_METRICS_GLOBAL_WORKERS = 2
    SPRINT_METRICS_JOB_DEADLINE_SECONDS = 10
    SPRINT_METRICS_CACHE_TTL_SECONDS = 300
    SPRINT_METRICS_MAX_ATTEMPTS = 2


AGGREGATES = {
    "original_commitment": {"sp": 40, "count": 10, "pages": 1},
    "completed_original": {"sp": 32, "count": 8, "pages": 1},
    "total_completed": {"sp": 44, "count": 11, "pages": 1},
    "added_scope": {"sp": 12, "count": 3, "keys": ["ABC-9"], "pages": 1},
    "removed_scope": {"sp": 4, "count": 1, "pages": 1},
}


def make_app(tmp_path, name="metric-jobs"):
    database = tmp_path / f"{name}.sqlite3"

    class TestConfig(MetricJobTestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database.as_posix()}"
        LOG_DIR = str(tmp_path / f"{name}-logs")

    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        user = User(
            eid="E100",
            email="metric-user@example.com",
            display_name="Metric User",
            active=True,
            deleted=False,
            password_hash="unused",
            jira_pat_enc=CryptoService(TestConfig.FERNET_KEY).encrypt("jira-pat"),
        )
        db.session.add(user)
        db.session.commit()
    return app


def wait_for_terminal(app, job_id, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with app.app_context():
            run = db.session.get(UserSprintMetricRun, job_id)
            if run is not None and run.status in {"succeeded", "partial", "failed"}:
                db.session.expunge(run)
                return run
        time.sleep(0.02)
    raise AssertionError(f"Metric job {job_id} did not finish within {timeout} seconds")


def start_job(coordinator, app, *, user_id=1, board_id=101, sprint_id=202):
    with app.app_context():
        run, cached, created = coordinator.start_or_reuse(
            user_id=user_id,
            board_id=board_id,
            sprint_id=sprint_id,
            total_sp=44,
            total_count=11,
            correlation_id=f"request-{user_id}-{sprint_id}",
        )
        return run.id, cached, created


def test_metric_job_preserves_partial_results_and_retries_only_failed_query(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    calls: dict[str, int] = {}

    def collect(self, *, metric_name, spec, pat, deadline_seconds):
        calls[metric_name] = calls.get(metric_name, 0) + 1
        assert pat == "jira-pat"
        assert deadline_seconds > 0
        if metric_name == "removed_scope" and calls[metric_name] == 1:
            raise SprintViewerServiceError("timed out") from ExternalServiceError(
                service="jira",
                operation="GET /rest/api/2/search",
                message="External request timed out",
                category="timeout",
                retryable=True,
            )
        return dict(AGGREGATES[metric_name])

    monkeypatch.setattr(SprintViewerService, "collect_metric_query", collect)
    coordinator = SprintMetricCoordinator(app)
    try:
        job_id, cached, created = start_job(coordinator, app)
        assert created is True
        assert cached is False

        partial = wait_for_terminal(app, job_id)
        assert partial.status == "partial"
        assert partial.error_code == "jira_timeout"
        assert partial.result_json["metrics"]["committed_sp"] == 40
        assert "spillover_sp" not in partial.result_json["metrics"]

        with app.app_context():
            retried = coordinator.retry(job_id, 1)
            assert retried is not None
            assert retried.status == "queued"

        succeeded = wait_for_terminal(app, job_id)
        assert succeeded.status == "succeeded"
        assert succeeded.result_json["metrics"]["spillover_sp"] == 4
        assert succeeded.attempt_count == 2
        assert calls["removed_scope"] == 2
        assert all(calls[name] == 1 for name in AGGREGATES if name != "removed_scope")

        same_job_id, cache_hit, cache_created = start_job(coordinator, app)
        assert same_job_id == job_id
        assert cache_hit is True
        assert cache_created is False
    finally:
        coordinator.shutdown(wait=True)


def test_metric_coordinator_never_runs_more_than_two_jira_queries(tmp_path, monkeypatch):
    app = make_app(tmp_path, "metric-concurrency")
    lock = threading.Lock()
    two_running = threading.Event()
    active = 0
    peak = 0

    def collect(self, *, metric_name, spec, pat, deadline_seconds):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active >= 2:
                two_running.set()
        two_running.wait(timeout=1)
        time.sleep(0.02)
        with lock:
            active -= 1
        return dict(AGGREGATES[metric_name])

    monkeypatch.setattr(SprintViewerService, "collect_metric_query", collect)
    coordinator = SprintMetricCoordinator(app)
    try:
        job_ids = [
            start_job(coordinator, app, sprint_id=sprint_id)[0] for sprint_id in (301, 302, 303)
        ]
        runs = [wait_for_terminal(app, job_id) for job_id in job_ids]

        assert all(run.status == "succeeded" for run in runs)
        assert peak == 2
        assert peak <= coordinator.max_workers == 2
    finally:
        coordinator.shutdown(wait=True)


def test_metric_cache_is_isolated_by_user(tmp_path, monkeypatch):
    app = make_app(tmp_path, "metric-cache")
    with app.app_context():
        second = User(
            eid="E200",
            email="other-metric-user@example.com",
            display_name="Other Metric User",
            active=True,
            deleted=False,
            password_hash="unused",
            jira_pat_enc=CryptoService(app.config["FERNET_KEY"]).encrypt("other-pat"),
        )
        db.session.add(second)
        db.session.commit()

    monkeypatch.setattr(
        SprintViewerService,
        "collect_metric_query",
        lambda self, *, metric_name, spec, pat, deadline_seconds: dict(AGGREGATES[metric_name]),
    )
    coordinator = SprintMetricCoordinator(app)
    try:
        first_id, _, _ = start_job(coordinator, app, user_id=1, sprint_id=401)
        assert wait_for_terminal(app, first_id).status == "succeeded"

        same_id, cache_hit, _ = start_job(coordinator, app, user_id=1, sprint_id=401)
        other_id, other_cache_hit, other_created = start_job(
            coordinator, app, user_id=2, sprint_id=401
        )

        assert same_id == first_id
        assert cache_hit is True
        assert other_id != first_id
        assert other_cache_hit is False
        assert other_created is True
        assert wait_for_terminal(app, other_id).status == "succeeded"
    finally:
        coordinator.shutdown(wait=True)


def test_only_latest_generation_can_be_reused(tmp_path, monkeypatch):
    app = make_app(tmp_path, "metric-generations")
    now = utc_now()
    with app.app_context():
        db.session.add_all(
            [
                UserSprintMetricRun(
                    id="1" * 32,
                    user_id=1,
                    board_id=101,
                    sprint_id=450,
                    metrics_version=METRICS_VERSION,
                    generation=1,
                    status="succeeded",
                    total_sp=44,
                    total_count=11,
                    progress_json=_initial_progress(),
                    result_json={"aggregates": AGGREGATES, "metrics": {"committed_sp": 40}},
                    attempt_count=1,
                    correlation_id="old-success",
                    cache_expires_at=now + timedelta(minutes=5),
                    finished_at=now,
                ),
                UserSprintMetricRun(
                    id="2" * 32,
                    user_id=1,
                    board_id=101,
                    sprint_id=450,
                    metrics_version=METRICS_VERSION,
                    generation=2,
                    status="partial",
                    total_sp=44,
                    total_count=11,
                    progress_json=_initial_progress(),
                    result_json={"aggregates": {}, "metrics": {}},
                    error_code="jira_timeout",
                    attempt_count=1,
                    correlation_id="latest-partial",
                    finished_at=now,
                ),
            ]
        )
        db.session.commit()

    monkeypatch.setattr(
        SprintViewerService,
        "collect_metric_query",
        lambda self, *, metric_name, spec, pat, deadline_seconds: dict(AGGREGATES[metric_name]),
    )
    coordinator = SprintMetricCoordinator(app)
    try:
        selected_id, cached, created = start_job(coordinator, app, sprint_id=450)
        assert selected_id == "2" * 32
        assert cached is False
        assert created is False

        with app.app_context():
            latest = db.session.get(UserSprintMetricRun, "2" * 32)
            latest.status = "succeeded"
            latest.cache_expires_at = now - timedelta(seconds=1)
            db.session.commit()

        fresh_id, fresh_cached, fresh_created = start_job(coordinator, app, sprint_id=450)
        assert fresh_id not in {"1" * 32, "2" * 32}
        assert fresh_cached is False
        assert fresh_created is True
        assert wait_for_terminal(app, fresh_id).status == "succeeded"
    finally:
        coordinator.shutdown(wait=True)


def test_recovery_reuses_successful_query_checkpoint(tmp_path, monkeypatch):
    app = make_app(tmp_path, "metric-recovery")
    progress = _initial_progress()
    progress["queries"]["original_commitment"].update(
        {"status": "succeeded", "duration_ms": 10, "pages": 1}
    )
    progress.update({"completed": 1, "succeeded": 1, "failed": 0})
    with app.app_context():
        db.session.add(
            UserSprintMetricRun(
                id="a" * 32,
                user_id=1,
                board_id=101,
                sprint_id=501,
                metrics_version=METRICS_VERSION,
                generation=1,
                status="running",
                total_sp=44,
                total_count=11,
                progress_json=progress,
                result_json={
                    "aggregates": {"original_commitment": dict(AGGREGATES["original_commitment"])},
                    "metrics": {"committed_sp": 40, "committed_count": 10},
                },
                attempt_count=1,
                correlation_id="recovery-request",
                started_at=utc_now(),
            )
        )
        db.session.commit()

    calls: list[str] = []

    def collect(self, *, metric_name, spec, pat, deadline_seconds):
        calls.append(metric_name)
        return dict(AGGREGATES[metric_name])

    monkeypatch.setattr(SprintViewerService, "collect_metric_query", collect)
    coordinator = SprintMetricCoordinator(app)
    try:
        coordinator.recover()
        recovered = wait_for_terminal(app, "a" * 32)

        assert recovered.status == "succeeded"
        assert recovered.attempt_count == 2
        assert "original_commitment" not in calls
        assert set(calls) == set(AGGREGATES) - {"original_commitment"}
    finally:
        coordinator.shutdown(wait=True)


def test_queued_metric_http_flow_returns_fast_polls_and_hits_cache(tmp_path, monkeypatch):
    app = make_app(tmp_path, "metric-http")
    with app.app_context():
        db.session.add(
            User(
                eid="E999",
                email="unauthorized-metric-user@example.com",
                display_name="Unauthorized Metric User",
                active=True,
                deleted=False,
                password_hash="unused",
                jira_pat_enc=CryptoService(app.config["FERNET_KEY"]).encrypt("other-pat"),
            )
        )
        project = UserProject(
            user_id=1,
            project_key="ABC",
            admin_projects=True,
            project_id=123,
            epic_key="ABC",
        )
        db.session.add(project)
        db.session.flush()
        db.session.add(
            UserBoard(
                project_id=project.id,
                board_id=101,
                board_name="HTTP Test Board",
                board_type="scrum",
            )
        )
        db.session.commit()

    def collect(self, *, metric_name, spec, pat, deadline_seconds):
        time.sleep(0.03)
        return dict(AGGREGATES[metric_name])

    monkeypatch.setattr(SprintViewerService, "collect_metric_query", collect)
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = "1"
        session["_fresh"] = True

    started = time.perf_counter()
    response = client.post(
        "/api/automation/sprint-viewer/metrics",
        json={"board_id": 101, "sprint_id": 601, "total_sp": 44, "total_count": 11},
    )
    start_duration = time.perf_counter() - started
    payload = response.get_json()

    assert response.status_code == 202
    assert start_duration < 1
    assert payload["job"]["status"] == "queued"
    job_id = payload["job"]["id"]

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status_response = client.get(f"/api/automation/sprint-viewer/metrics/{job_id}")
        status_payload = status_response.get_json()
        if status_payload["job"]["status"] == "succeeded":
            break
        time.sleep(0.02)
    else:
        raise AssertionError("HTTP metric job did not complete")

    assert status_response.status_code == 200
    assert status_response.headers["Cache-Control"] == "no-store"
    assert status_payload["metrics"]["committed_sp"] == 40

    cached_response = client.post(
        "/api/automation/sprint-viewer/metrics",
        json={"board_id": 101, "sprint_id": 601, "total_sp": 44, "total_count": 11},
    )
    cached_payload = cached_response.get_json()

    assert cached_response.status_code == 200
    assert cached_payload["job"]["id"] == job_id
    assert cached_payload["cached"] is True

    with client.session_transaction() as session:
        session["_user_id"] = "2"
        session["_fresh"] = True
    unauthorized_status = client.get(f"/api/automation/sprint-viewer/metrics/{job_id}")
    unauthorized_retry = client.post(
        f"/api/automation/sprint-viewer/metrics/{job_id}/retry", json={}
    )
    assert unauthorized_status.status_code == 404
    assert unauthorized_retry.status_code == 404

    coordinator = app.extensions.get("sprint_metric_coordinator")
    if coordinator is not None:
        coordinator.shutdown(wait=True)
