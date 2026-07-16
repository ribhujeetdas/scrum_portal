from __future__ import annotations

import atexit
import copy
import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import Flask, current_app
from sqlalchemy import func

from ....core.database import execute_write
from ....core.http_client import ExternalServiceError
from ....extensions import db
from ....logging_conf import set_request_id
from ....models import User, UserSprintMetricRun, utc_now
from ....services.crypto_service import CryptoService
from ....services.sprint_viewer_service import SprintViewerService, SprintViewerServiceError
from .metrics import METRIC_QUERY_NAMES, build_available_scrum_metrics

METRICS_VERSION = "scrum-v1"
ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("succeeded", "partial", "failed", "interrupted")
RETRYABLE_STATUSES = ("partial", "failed", "interrupted")

_LOGGER = logging.getLogger("app.sprint_metrics")


def _initial_progress() -> dict[str, Any]:
    return {
        "total": len(METRIC_QUERY_NAMES),
        "completed": 0,
        "succeeded": 0,
        "failed": 0,
        "queries": {
            name: {
                "status": "pending",
                "duration_ms": None,
                "pages": 0,
                "error_code": None,
            }
            for name in METRIC_QUERY_NAMES
        },
    }


def _normalized_progress(value: Any) -> dict[str, Any]:
    progress = copy.deepcopy(value) if isinstance(value, dict) else _initial_progress()
    queries = progress.setdefault("queries", {})
    for name in METRIC_QUERY_NAMES:
        queries.setdefault(
            name,
            {
                "status": "pending",
                "duration_ms": None,
                "pages": 0,
                "error_code": None,
            },
        )
    _refresh_progress_counts(progress)
    return progress


def _refresh_progress_counts(progress: dict[str, Any]) -> None:
    states = [
        str((progress.get("queries") or {}).get(name, {}).get("status") or "pending")
        for name in METRIC_QUERY_NAMES
    ]
    progress["total"] = len(METRIC_QUERY_NAMES)
    progress["succeeded"] = states.count("succeeded")
    progress["failed"] = states.count("failed")
    progress["completed"] = progress["succeeded"] + progress["failed"]


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def safe_metric_error_message(code: str | None) -> str | None:
    messages = {
        "jira_timeout": "Jira took too long to calculate one or more metrics.",
        "jira_rate_limited": "Jira temporarily rate-limited the metric calculation.",
        "jira_unavailable": "Jira is temporarily unavailable for metric calculation.",
        "jira_circuit_open": "Jira requests are temporarily paused after repeated failures.",
        "jira_busy": "The Jira request capacity is currently busy.",
        "jira_unauthorized": "Your Jira access token was rejected. Update it in Profile.",
        "jira_forbidden": "Your Jira account cannot run one or more sprint metric queries.",
        "jira_invalid_response": "Jira returned an invalid response for a metric query.",
        "job_deadline_exceeded": "Metric calculation exceeded its safe time limit.",
        "missing_jira_pat": "Set your Enterprise Agile Jira PAT in Profile.",
        "credential_decryption_failed": "The saved Jira token could not be read.",
        "worker_interrupted": "Metric calculation was interrupted by an application restart.",
        "internal_error": "Metric calculation failed unexpectedly.",
    }
    return (
        messages.get(code, "One or more sprint metrics could not be calculated.") if code else None
    )


def classify_metric_error(exc: BaseException) -> str:
    current: BaseException | None = exc
    external: ExternalServiceError | None = None
    while current is not None:
        if isinstance(current, ExternalServiceError):
            external = current
            break
        current = current.__cause__
    if external is None:
        return "internal_error"
    if external.status_code == 401:
        return "jira_unauthorized"
    if external.status_code == 403:
        return "jira_forbidden"
    if external.status_code == 429:
        return "jira_rate_limited"
    if external.status_code is not None and external.status_code >= 500:
        return "jira_unavailable"
    return {
        "timeout": "jira_timeout",
        "circuit_open": "jira_circuit_open",
        "bulkhead_rejected": "jira_busy",
        "invalid_json": "jira_invalid_response",
        "operation_budget_exceeded": "job_deadline_exceeded",
    }.get(external.category, "jira_unavailable")


def serialize_metric_run(
    run: UserSprintMetricRun,
    *,
    cached: bool = False,
    max_attempts: int | None = None,
) -> dict[str, Any]:
    result = run.result_json if isinstance(run.result_json, dict) else {}
    error_message = safe_metric_error_message(run.error_code)
    return {
        "id": run.id,
        "status": run.status,
        "cached": bool(cached),
        "metrics": result.get("metrics") if isinstance(result.get("metrics"), dict) else None,
        "progress": _normalized_progress(run.progress_json),
        "error": (
            {"code": run.error_code, "message": error_message}
            if run.error_code and error_message
            else None
        ),
        "attempt_count": int(run.attempt_count or 0),
        "max_attempts": int(
            max_attempts
            if max_attempts is not None
            else current_app.config.get("SPRINT_METRICS_MAX_ATTEMPTS", 2)
        ),
        "created_at": _iso(run.created_at),
        "updated_at": _iso(run.updated_at),
        "finished_at": _iso(run.finished_at),
        "cache_expires_at": _iso(run.cache_expires_at),
    }


class SprintMetricRunRepository:
    def get_owned(self, job_id: str, user_id: int) -> UserSprintMetricRun | None:
        return UserSprintMetricRun.query.filter_by(id=job_id, user_id=user_id).first()

    def find_active(
        self, user_id: int, board_id: int, sprint_id: int
    ) -> UserSprintMetricRun | None:
        return (
            UserSprintMetricRun.query.filter(
                UserSprintMetricRun.user_id == user_id,
                UserSprintMetricRun.board_id == board_id,
                UserSprintMetricRun.sprint_id == sprint_id,
                UserSprintMetricRun.metrics_version == METRICS_VERSION,
                UserSprintMetricRun.status.in_(ACTIVE_STATUSES),
            )
            .order_by(UserSprintMetricRun.created_at.desc())
            .first()
        )

    def find_latest(
        self, user_id: int, board_id: int, sprint_id: int
    ) -> UserSprintMetricRun | None:
        return (
            UserSprintMetricRun.query.filter(
                UserSprintMetricRun.user_id == user_id,
                UserSprintMetricRun.board_id == board_id,
                UserSprintMetricRun.sprint_id == sprint_id,
                UserSprintMetricRun.metrics_version == METRICS_VERSION,
            )
            .order_by(UserSprintMetricRun.generation.desc())
            .first()
        )

    def next_generation(self, user_id: int, board_id: int, sprint_id: int) -> int:
        latest = (
            db.session.query(func.max(UserSprintMetricRun.generation))
            .filter_by(
                user_id=user_id,
                board_id=board_id,
                sprint_id=sprint_id,
                metrics_version=METRICS_VERSION,
            )
            .scalar()
        )
        return int(latest or 0) + 1


class SprintMetricCoordinator:
    """Process-local coordinator backed by durable SQLite job checkpoints."""

    def __init__(self, app: Flask):
        self.app = app
        self.max_workers = max(1, min(int(app.config.get("SPRINT_METRICS_GLOBAL_WORKERS", 2)), 2))
        self.max_attempts = int(app.config.get("SPRINT_METRICS_MAX_ATTEMPTS", 2))
        self.deadline_seconds = int(app.config.get("SPRINT_METRICS_JOB_DEADLINE_SECONDS", 180))
        self.cache_ttl_seconds = int(app.config.get("SPRINT_METRICS_CACHE_TTL_SECONDS", 86400))
        self.retention_days = int(app.config.get("SPRINT_METRICS_RUN_RETENTION_DAYS", 30))
        self.repository = SprintMetricRunRepository()
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="sprint-metrics",
        )
        self._futures: dict[str, Future] = {}
        self._future_lock = threading.RLock()
        self._creation_lock = threading.RLock()
        self._recovered = False
        self._recovery_lock = threading.Lock()
        self._shutdown = False
        atexit.register(self.shutdown)

    def queue_depth(self) -> int:
        with self._future_lock:
            return sum(1 for future in self._futures.values() if not future.done())

    def recover(self) -> None:
        with self._recovery_lock:
            if self._recovered:
                return
            self._recovered = True
            with self.app.app_context():
                queued_ids: list[str] = []

                def recover_rows() -> None:
                    rows = UserSprintMetricRun.query.filter(
                        UserSprintMetricRun.status.in_(ACTIVE_STATUSES)
                    ).all()
                    for row in rows:
                        if row.status == "running":
                            row.status = "interrupted"
                            row.error_code = "worker_interrupted"
                            row.finished_at = utc_now()
                        if int(row.attempt_count or 0) < self.max_attempts:
                            row.status = "queued"
                            row.error_code = None
                            row.finished_at = None
                            queued_ids.append(row.id)
                        else:
                            row.status = "failed"

                execute_write(recover_rows)
                db.session.remove()
            for job_id in queued_ids:
                self.enqueue(job_id)
            if queued_ids:
                _LOGGER.info(
                    "Recovered interrupted Sprint metric jobs",
                    extra={
                        "event": "sprint_metrics.recovered",
                        "context": {"job_count": len(queued_ids)},
                    },
                )

    def start_or_reuse(
        self,
        *,
        user_id: int,
        board_id: int,
        sprint_id: int,
        total_sp: float,
        total_count: int,
        correlation_id: str,
        force_refresh: bool = False,
    ) -> tuple[UserSprintMetricRun, bool, bool]:
        self.recover()
        with self._creation_lock:
            now = utc_now()
            run = self.repository.find_active(user_id, board_id, sprint_id)
            if run is not None:
                self.enqueue(run.id)
                return run, False, False

            if not force_refresh:
                run = self.repository.find_latest(user_id, board_id, sprint_id)
                cache_expiry = run.cache_expires_at if run is not None else None
                if cache_expiry is not None and cache_expiry.tzinfo is None:
                    cache_expiry = cache_expiry.replace(tzinfo=UTC)
                if (
                    run is not None
                    and run.status == "succeeded"
                    and cache_expiry is not None
                    and cache_expiry > now
                ):
                    _LOGGER.info(
                        "Sprint metric cache hit",
                        extra={
                            "event": "sprint_metrics.cache.hit",
                            "user_id": user_id,
                            "context": {
                                "job_id": run.id,
                                "board_id": board_id,
                                "sprint_id": sprint_id,
                            },
                        },
                    )
                    return run, True, False
                if run is not None and run.status == "partial":
                    return run, False, False

            _LOGGER.info(
                "Sprint metric cache miss",
                extra={
                    "event": "sprint_metrics.cache.miss",
                    "user_id": user_id,
                    "context": {
                        "board_id": board_id,
                        "sprint_id": sprint_id,
                        "force_refresh": force_refresh,
                    },
                },
            )

            generation = self.repository.next_generation(user_id, board_id, sprint_id)
            run = UserSprintMetricRun(
                id=uuid.uuid4().hex,
                user_id=user_id,
                board_id=board_id,
                sprint_id=sprint_id,
                metrics_version=METRICS_VERSION,
                generation=generation,
                status="queued",
                total_sp=total_sp,
                total_count=total_count,
                progress_json=_initial_progress(),
                result_json={"aggregates": {}, "metrics": {}},
                attempt_count=0,
                correlation_id=str(correlation_id or uuid.uuid4().hex)[:64],
            )

            def create_run() -> None:
                cutoff = now - timedelta(days=self.retention_days)
                UserSprintMetricRun.query.filter(
                    UserSprintMetricRun.status.in_(TERMINAL_STATUSES),
                    UserSprintMetricRun.updated_at < cutoff,
                ).delete(synchronize_session=False)
                db.session.add(run)

            execute_write(create_run)
            _LOGGER.info(
                "Sprint metric job queued",
                extra={
                    "event": "sprint_metrics.job.queued",
                    "user_id": user_id,
                    "context": {
                        "job_id": run.id,
                        "board_id": board_id,
                        "sprint_id": sprint_id,
                        "generation": generation,
                        "queue_depth": self.queue_depth() + 1,
                    },
                },
            )
            self.enqueue(run.id)
            return run, False, True

    def enqueue(self, job_id: str) -> None:
        if self._shutdown:
            return
        with self._future_lock:
            current = self._futures.get(job_id)
            if current is not None and not current.done():
                return
            future = self._executor.submit(self._run_job_guarded, job_id)
            self._futures[job_id] = future
            future.add_done_callback(
                lambda done, selected=job_id: self._future_done(selected, done)
            )

    def retry(self, job_id: str, user_id: int) -> UserSprintMetricRun | None:
        self.recover()
        with self._creation_lock:
            run = self.repository.get_owned(job_id, user_id)
            if run is None:
                return None
            if run.status not in RETRYABLE_STATUSES:
                return run
            if int(run.attempt_count or 0) >= self.max_attempts:
                return run

            def queue_retry() -> None:
                progress = _normalized_progress(run.progress_json)
                for query in progress["queries"].values():
                    if query.get("status") != "succeeded":
                        query.update(
                            {
                                "status": "pending",
                                "duration_ms": None,
                                "pages": 0,
                                "error_code": None,
                            }
                        )
                _refresh_progress_counts(progress)
                run.progress_json = progress
                run.status = "queued"
                run.error_code = None
                run.finished_at = None
                run.cache_expires_at = None

            execute_write(queue_retry)
            self.enqueue(run.id)
            return run

    def ensure_enqueued(self, run: UserSprintMetricRun) -> None:
        if run.status == "queued":
            self.enqueue(run.id)

    def _future_done(self, job_id: str, future: Future) -> None:
        with self._future_lock:
            self._futures.pop(job_id, None)
        exc = None if future.cancelled() else future.exception()
        if exc is not None:
            _LOGGER.error(
                "Sprint metric worker future failed",
                exc_info=(type(exc), exc, exc.__traceback__),
                extra={
                    "event": "sprint_metrics.worker.failed",
                    "context": {"job_id": job_id},
                },
            )
        if self._shutdown:
            return
        # A user can request a retry in the small interval after the worker
        # persists a terminal state but before this callback runs. If retry()
        # changed it back to queued, submit it now that the old future is gone.
        with self.app.app_context():
            run = db.session.get(UserSprintMetricRun, job_id)
            should_requeue = run is not None and run.status == "queued"
            db.session.remove()
        if should_requeue:
            self.enqueue(job_id)

    def _run_job_guarded(self, job_id: str) -> None:
        with self.app.app_context():
            try:
                self._run_job(job_id)
            except Exception as exc:
                db.session.rollback()
                self._finish_unexpected(job_id)
                _LOGGER.error(
                    "Sprint metric job failed unexpectedly",
                    exc_info=(type(exc), exc, exc.__traceback__),
                    extra={
                        "event": "sprint_metrics.job.unexpected_failure",
                        "context": {"job_id": job_id},
                    },
                )
            finally:
                db.session.remove()
                set_request_id("-")

    def _run_job(self, job_id: str) -> None:
        job_context: dict[str, Any] = {}

        def begin_job() -> None:
            run = db.session.get(UserSprintMetricRun, job_id)
            if run is None or run.status != "queued":
                return
            if int(run.attempt_count or 0) >= self.max_attempts:
                run.status = "failed"
                run.error_code = run.error_code or "internal_error"
                run.finished_at = utc_now()
                return
            progress = _normalized_progress(run.progress_json)
            for query in progress["queries"].values():
                if query.get("status") != "succeeded":
                    query["status"] = "pending"
                    query["error_code"] = None
            _refresh_progress_counts(progress)
            run.progress_json = progress
            run.status = "running"
            run.attempt_count = int(run.attempt_count or 0) + 1
            run.started_at = utc_now()
            run.finished_at = None
            run.error_code = None
            result = run.result_json if isinstance(run.result_json, dict) else {}
            job_context.update(
                {
                    "user_id": run.user_id,
                    "board_id": run.board_id,
                    "sprint_id": run.sprint_id,
                    "attempt": run.attempt_count,
                    "correlation_id": run.correlation_id,
                    "progress": progress,
                    "aggregates": copy.deepcopy(result.get("aggregates") or {}),
                }
            )

        execute_write(begin_job)
        if not job_context:
            return
        set_request_id(job_context["correlation_id"])
        _LOGGER.info(
            "Sprint metric job started",
            extra={
                "event": "sprint_metrics.job.started",
                "user_id": job_context["user_id"],
                "context": {
                    "job_id": job_id,
                    "board_id": job_context["board_id"],
                    "sprint_id": job_context["sprint_id"],
                    "attempt": job_context["attempt"],
                    "queue_depth": self.queue_depth(),
                },
            },
        )

        user = db.session.get(User, job_context["user_id"])
        if user is None or not user.jira_pat_enc:
            self._finish_with_code(job_id, "missing_jira_pat")
            return
        try:
            pat = CryptoService(current_app.config["FERNET_KEY"]).decrypt(user.jira_pat_enc)
        except ValueError:
            self._finish_with_code(job_id, "credential_decryption_failed")
            return
        finally:
            db.session.remove()

        service = SprintViewerService(
            current_app.config["JIRA_BASE_URL"],
            timeout_seconds=current_app.config.get("SPRINT_METRICS_READ_TIMEOUT_SECONDS", 45),
            metrics_max_workers=current_app.config.get("SPRINT_METRICS_MAX_WORKERS", 3),
        )
        specs = service.metric_query_specs(job_context["board_id"], job_context["sprint_id"])
        started = time.monotonic()
        stop_code: str | None = None

        for name in METRIC_QUERY_NAMES:
            if job_context["progress"]["queries"][name].get("status") == "succeeded":
                continue
            remaining = self.deadline_seconds - (time.monotonic() - started)
            if remaining <= 1:
                stop_code = "job_deadline_exceeded"
                break
            self._checkpoint_query_running(job_id, job_context, name)
            query_started = time.perf_counter()
            _LOGGER.info(
                "Sprint metric query started",
                extra={
                    "event": "sprint_metrics.query.started",
                    "user_id": job_context["user_id"],
                    "context": {
                        "job_id": job_id,
                        "board_id": job_context["board_id"],
                        "sprint_id": job_context["sprint_id"],
                        "metric_name": name,
                        "attempt": job_context["attempt"],
                    },
                },
            )
            try:
                aggregate = service.collect_metric_query(
                    metric_name=name,
                    spec=specs[name],
                    pat=pat,
                    deadline_seconds=max(1.0, remaining),
                )
            except SprintViewerServiceError as exc:
                duration_ms = int((time.perf_counter() - query_started) * 1000)
                code = classify_metric_error(exc)
                self._checkpoint_query_failure(job_id, job_context, name, code, duration_ms)
                _LOGGER.warning(
                    "Sprint metric query failed",
                    extra={
                        "event": "sprint_metrics.query.failed",
                        "user_id": job_context["user_id"],
                        "duration_ms": duration_ms,
                        "category": code,
                        "context": {
                            "job_id": job_id,
                            "board_id": job_context["board_id"],
                            "sprint_id": job_context["sprint_id"],
                            "metric_name": name,
                            "attempt": job_context["attempt"],
                        },
                    },
                )
                if code in {"jira_unauthorized", "jira_forbidden"}:
                    stop_code = code
                    break
                continue

            duration_ms = int((time.perf_counter() - query_started) * 1000)
            self._checkpoint_query_success(job_id, job_context, name, aggregate, duration_ms)
            _LOGGER.info(
                "Sprint metric query completed",
                extra={
                    "event": "sprint_metrics.query.completed",
                    "user_id": job_context["user_id"],
                    "duration_ms": duration_ms,
                    "context": {
                        "job_id": job_id,
                        "board_id": job_context["board_id"],
                        "sprint_id": job_context["sprint_id"],
                        "metric_name": name,
                        "attempt": job_context["attempt"],
                        "pages": int(aggregate.get("pages") or 0),
                        "result_count": int(aggregate.get("count") or 0),
                    },
                },
            )

        if stop_code:
            self._mark_remaining_failed(job_id, job_context, stop_code)
        self._finalize(job_id, job_context)

    def _checkpoint_query_running(self, job_id: str, context: dict[str, Any], name: str) -> None:
        query = context["progress"]["queries"][name]
        query.update({"status": "running", "error_code": None})
        self._persist_checkpoint(job_id, context)

    def _checkpoint_query_success(
        self,
        job_id: str,
        context: dict[str, Any],
        name: str,
        aggregate: dict[str, Any],
        duration_ms: int,
    ) -> None:
        context["aggregates"][name] = copy.deepcopy(aggregate)
        context["progress"]["queries"][name].update(
            {
                "status": "succeeded",
                "duration_ms": duration_ms,
                "pages": int(aggregate.get("pages") or 0),
                "error_code": None,
            }
        )
        self._persist_checkpoint(job_id, context)

    def _checkpoint_query_failure(
        self,
        job_id: str,
        context: dict[str, Any],
        name: str,
        code: str,
        duration_ms: int,
    ) -> None:
        context["progress"]["queries"][name].update(
            {
                "status": "failed",
                "duration_ms": duration_ms,
                "pages": 0,
                "error_code": code,
            }
        )
        self._persist_checkpoint(job_id, context)

    def _mark_remaining_failed(self, job_id: str, context: dict[str, Any], code: str) -> None:
        for query in context["progress"]["queries"].values():
            if query.get("status") not in {"succeeded", "failed"}:
                query.update(
                    {"status": "failed", "duration_ms": None, "pages": 0, "error_code": code}
                )
        self._persist_checkpoint(job_id, context)

    def _persist_checkpoint(self, job_id: str, context: dict[str, Any]) -> None:
        _refresh_progress_counts(context["progress"])
        metrics = build_available_scrum_metrics(context["aggregates"])

        def save() -> None:
            run = db.session.get(UserSprintMetricRun, job_id)
            if run is None:
                return
            run.progress_json = copy.deepcopy(context["progress"])
            run.result_json = {
                "aggregates": copy.deepcopy(context["aggregates"]),
                "metrics": metrics,
            }

        execute_write(save)
        db.session.remove()

    def _finalize(self, job_id: str, context: dict[str, Any]) -> None:
        _refresh_progress_counts(context["progress"])
        succeeded = int(context["progress"]["succeeded"])
        failed_codes = [
            query.get("error_code")
            for query in context["progress"]["queries"].values()
            if query.get("status") == "failed" and query.get("error_code")
        ]
        status = (
            "succeeded"
            if succeeded == len(METRIC_QUERY_NAMES)
            else ("partial" if succeeded else "failed")
        )
        now = utc_now()

        def finish() -> None:
            run = db.session.get(UserSprintMetricRun, job_id)
            if run is None:
                return
            run.progress_json = copy.deepcopy(context["progress"])
            run.result_json = {
                "aggregates": copy.deepcopy(context["aggregates"]),
                "metrics": build_available_scrum_metrics(context["aggregates"]),
            }
            run.status = status
            run.error_code = failed_codes[0] if failed_codes else None
            run.finished_at = now
            run.cache_expires_at = (
                now + timedelta(seconds=self.cache_ttl_seconds) if status == "succeeded" else None
            )

        execute_write(finish)
        _LOGGER.info(
            "Sprint metric job finished",
            extra={
                "event": "sprint_metrics.job.finished",
                "user_id": context["user_id"],
                "result": status,
                "category": failed_codes[0] if failed_codes else None,
                "context": {
                    "job_id": job_id,
                    "board_id": context["board_id"],
                    "sprint_id": context["sprint_id"],
                    "attempt": context["attempt"],
                    "succeeded_queries": succeeded,
                    "failed_queries": len(METRIC_QUERY_NAMES) - succeeded,
                },
            },
        )

    def _finish_with_code(self, job_id: str, code: str) -> None:
        def finish() -> None:
            run = db.session.get(UserSprintMetricRun, job_id)
            if run is None:
                return
            progress = _normalized_progress(run.progress_json)
            for query in progress["queries"].values():
                if query.get("status") != "succeeded":
                    query.update(
                        {"status": "failed", "duration_ms": None, "pages": 0, "error_code": code}
                    )
            _refresh_progress_counts(progress)
            run.progress_json = progress
            run.status = "partial" if progress["succeeded"] else "failed"
            run.error_code = code
            run.finished_at = utc_now()
            run.cache_expires_at = None

        execute_write(finish)

    def _finish_unexpected(self, job_id: str) -> None:
        try:
            self._finish_with_code(job_id, "internal_error")
        except Exception:
            db.session.rollback()

    def shutdown(self, wait: bool = False) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._executor.shutdown(wait=wait, cancel_futures=True)


def get_sprint_metric_coordinator() -> SprintMetricCoordinator:
    app = current_app._get_current_object()
    coordinator = app.extensions.get("sprint_metric_coordinator")
    if coordinator is None:
        coordinator = SprintMetricCoordinator(app)
        app.extensions["sprint_metric_coordinator"] = coordinator
    return coordinator
