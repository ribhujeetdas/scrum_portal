import logging
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from flask import current_app, has_app_context
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .redaction import redact

_BULKHEADS: dict[tuple[str, int], threading.BoundedSemaphore] = {}
_BULKHEADS_LOCK = threading.Lock()
_CIRCUITS_LOCK = threading.Lock()


@dataclass
class _CircuitState:
    failures: int = 0
    opened_at: float | None = None


_CIRCUITS: dict[tuple[str, str], _CircuitState] = {}


def redact_text(value: Any) -> Any:
    return redact(value)


class ExternalServiceError(Exception):
    def __init__(
        self,
        *,
        service: str,
        operation: str,
        message: str,
        status_code: int | None = None,
        response_snippet: str | None = None,
        endpoint: str | None = None,
        category: str = "external_service_error",
        retryable: bool = False,
    ):
        self.service = service
        self.operation = operation
        self.message = message
        self.status_code = status_code
        self.response_snippet = response_snippet
        self.endpoint = endpoint
        self.category = category
        self.retryable = retryable
        parts = [f"{service} {operation}: {message}"]
        if status_code is not None:
            parts.append(f"status={status_code}")
        if response_snippet:
            parts.append(f"response={response_snippet}")
        super().__init__("; ".join(parts))


class ExternalOperationBudget:
    """Bound pagination so a bad upstream cannot consume a worker indefinitely."""

    def __init__(
        self,
        service: str,
        operation: str,
        *,
        max_pages: int | None = None,
        deadline_seconds: float | None = None,
    ):
        self.service = service
        self.operation = operation
        self.max_pages = ExternalHttpClient._config_int(
            "EXTERNAL_OPERATION_MAX_PAGES", 100, max_pages
        )
        self.deadline_seconds = ExternalHttpClient._config_float(
            "EXTERNAL_OPERATION_DEADLINE_SECONDS", 120.0, deadline_seconds
        )
        self._pages = 0
        self._started = time.monotonic()

    def next_page(self) -> None:
        self._pages += 1
        elapsed = time.monotonic() - self._started
        if self._pages > self.max_pages or elapsed > self.deadline_seconds:
            raise ExternalServiceError(
                service=self.service,
                operation=self.operation,
                message="External operation safety budget exceeded",
                category="operation_budget_exceeded",
                retryable=True,
            )


class ExternalHttpClient:
    def __init__(
        self,
        service: str,
        base_url: str,
        *,
        session: requests.Session | None = None,
        timeout_seconds: int = 10,
        connect_timeout_seconds: int | None = None,
        retry_total: int | None = None,
        retry_backoff_factor: float | None = None,
        retry_status_forcelist: tuple[int, ...] | None = None,
        retry_allowed_methods: tuple[str, ...] = ("GET", "HEAD", "OPTIONS"),
        max_concurrent: int | None = None,
        bulkhead_wait_seconds: float | None = None,
        circuit_failure_threshold: int | None = None,
        circuit_reset_seconds: int | None = None,
    ):
        self.service = service
        self.base_url = self._validate_base_url(base_url)
        self.timeout_seconds = timeout_seconds
        self.connect_timeout_seconds = connect_timeout_seconds
        self.retry_total = self._config_int("EXTERNAL_HTTP_RETRY_TOTAL", 3, retry_total)
        self.retry_backoff_factor = self._config_float(
            "EXTERNAL_HTTP_RETRY_BACKOFF_SECONDS", 0.5, retry_backoff_factor
        )
        self.retry_status_forcelist = (
            retry_status_forcelist
            if retry_status_forcelist is not None
            else self._config_status_codes(
                "EXTERNAL_HTTP_RETRY_STATUS_CODES", (429, 500, 502, 503, 504)
            )
        )
        self.retry_allowed_methods = retry_allowed_methods
        self.max_concurrent = self._config_int("EXTERNAL_HTTP_MAX_CONCURRENT", 12, max_concurrent)
        self.bulkhead_wait_seconds = self._config_float(
            "EXTERNAL_HTTP_BULKHEAD_WAIT_SECONDS", 1.0, bulkhead_wait_seconds
        )
        self.circuit_failure_threshold = self._config_int(
            "EXTERNAL_HTTP_CIRCUIT_FAILURE_THRESHOLD",
            5,
            circuit_failure_threshold,
        )
        self.circuit_reset_seconds = self._config_int(
            "EXTERNAL_HTTP_CIRCUIT_RESET_SECONDS", 30, circuit_reset_seconds
        )
        with _BULKHEADS_LOCK:
            self._bulkhead = _BULKHEADS.setdefault(
                (self.service, self.max_concurrent),
                threading.BoundedSemaphore(self.max_concurrent),
            )
        self._session = session or self._build_session()
        self._logger = logging.getLogger("app.external")
        self._circuit_key = (self.service, self.base_url)
        with _CIRCUITS_LOCK:
            _CIRCUITS.setdefault(self._circuit_key, _CircuitState())

    @staticmethod
    def _config_int(name: str, default: int, explicit: int | None = None) -> int:
        if explicit is not None:
            return int(explicit)
        if has_app_context():
            return int(current_app.config.get(name, default))
        return default

    @staticmethod
    def _config_float(name: str, default: float, explicit: float | None = None) -> float:
        if explicit is not None:
            return float(explicit)
        if has_app_context():
            return float(current_app.config.get(name, default))
        return default

    @staticmethod
    def _config_status_codes(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
        value = current_app.config.get(name, default) if has_app_context() else default
        if isinstance(value, str):
            return tuple(int(part.strip()) for part in value.split(",") if part.strip())
        return tuple(int(part) for part in value)

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(
            total=self.retry_total,
            backoff_factor=self.retry_backoff_factor,
            status_forcelist=self.retry_status_forcelist,
            allowed_methods=self.retry_allowed_methods,
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        session.mount("https://", HTTPAdapter(max_retries=retries))
        session.mount("http://", HTTPAdapter(max_retries=retries))
        return session

    def get_json(self, path: str, **kwargs: Any) -> Any:
        return self._request_json("GET", path, **kwargs)

    def post_json(self, path: str, **kwargs: Any) -> Any:
        return self._request_json("POST", path, **kwargs)

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.request(method, path, **kwargs)
        endpoint = self._safe_endpoint(path)

        try:
            return response.json()
        except ValueError as exc:
            self._record_circuit_failure()
            snippet = str(redact_text(response.text[:500]))
            self._log_failure(
                event=f"{self.service}.response.invalid_json",
                operation=f"{method} {endpoint}",
                endpoint=endpoint,
                status_code=response.status_code,
                response_snippet=snippet,
                message="External API returned invalid JSON",
                category="invalid_json",
            )
            raise ExternalServiceError(
                service=self.service,
                operation=f"{method} {endpoint}",
                message="Invalid JSON response",
                status_code=response.status_code,
                response_snippet=snippet,
                endpoint=endpoint,
                category="invalid_json",
            ) from exc

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        method = method.upper()
        endpoint = self._safe_endpoint(path)
        operation = f"{method} {endpoint}"
        if self.connect_timeout_seconds is None:
            kwargs.setdefault("timeout", self.timeout_seconds)
        else:
            kwargs.setdefault("timeout", (self.connect_timeout_seconds, self.timeout_seconds))
        kwargs.setdefault("allow_redirects", False)
        url = self._validated_url(path)
        self._ensure_circuit_available(operation, endpoint)
        acquired = self._bulkhead.acquire(timeout=self.bulkhead_wait_seconds)
        if not acquired:
            self._log_failure(
                event=f"{self.service}.request.bulkhead_rejected",
                operation=operation,
                endpoint=endpoint,
                message="External service concurrency limit reached",
                category="bulkhead_rejected",
                retryable=True,
            )
            raise ExternalServiceError(
                service=self.service,
                operation=operation,
                message="External service concurrency limit reached",
                endpoint=endpoint,
                category="bulkhead_rejected",
                retryable=True,
            )

        started = time.perf_counter()
        try:
            try:
                response = getattr(self._session, method.lower())(url, **kwargs)
            except requests.Timeout as exc:
                self._record_circuit_failure()
                self._log_failure(
                    event=f"{self.service}.request.failed",
                    operation=operation,
                    endpoint=endpoint,
                    message="External request timed out",
                    category="timeout",
                    retryable=True,
                )
                raise ExternalServiceError(
                    service=self.service,
                    operation=operation,
                    message="External request timed out",
                    endpoint=endpoint,
                    category="timeout",
                    retryable=True,
                ) from exc
            except requests.RequestException as exc:
                self._record_circuit_failure()
                self._log_failure(
                    event=f"{self.service}.request.failed",
                    operation=operation,
                    endpoint=endpoint,
                    message=str(redact_text(str(exc))),
                    category="connection_error",
                    retryable=True,
                )
                raise ExternalServiceError(
                    service=self.service,
                    operation=operation,
                    message=str(redact_text(str(exc))),
                    endpoint=endpoint,
                    category="connection_error",
                    retryable=True,
                ) from exc
        finally:
            self._bulkhead.release()

        duration_ms = int((time.perf_counter() - started) * 1000)

        if 300 <= response.status_code < 400:
            location = (
                str(redact_text(response.headers.get("Location", "")))
                if hasattr(response, "headers")
                else ""
            )
            self._log_failure(
                event=f"{self.service}.request.redirect_rejected",
                operation=operation,
                endpoint=endpoint,
                status_code=response.status_code,
                response_snippet=location[:500],
                category="redirect_rejected",
            )
            raise ExternalServiceError(
                service=self.service,
                operation=operation,
                message="External redirect rejected",
                status_code=response.status_code,
                response_snippet=location[:500],
                endpoint=endpoint,
                category="redirect_rejected",
            )

        if response.status_code >= 400:
            if response.status_code in self.retry_status_forcelist:
                self._record_circuit_failure()
            snippet = str(redact_text(response.text[:500]))
            self._log_failure(
                event=f"{self.service}.request.failed",
                operation=operation,
                endpoint=endpoint,
                status_code=response.status_code,
                response_snippet=snippet,
                category="http_error",
                retryable=response.status_code in self.retry_status_forcelist,
            )
            raise ExternalServiceError(
                service=self.service,
                operation=operation,
                message="HTTP request failed",
                status_code=response.status_code,
                response_snippet=snippet,
                endpoint=endpoint,
                category="http_error",
                retryable=response.status_code in self.retry_status_forcelist,
            )

        self._record_circuit_success()
        self._logger.info(
            "External API request complete",
            extra={
                "event": f"{self.service}.request.complete",
                "external_service": self.service,
                "external_operation": operation,
                "external_endpoint": endpoint,
                "external_status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )

        return response

    def _ensure_circuit_available(self, operation: str, endpoint: str) -> None:
        now = time.monotonic()
        with _CIRCUITS_LOCK:
            state = _CIRCUITS[self._circuit_key]
            if state.opened_at is None:
                return
            if now - state.opened_at >= self.circuit_reset_seconds:
                state.failures = 0
                state.opened_at = None
                return
        self._log_failure(
            event=f"{self.service}.request.circuit_open",
            operation=operation,
            endpoint=endpoint,
            message="External service circuit is temporarily open",
            category="circuit_open",
            retryable=True,
        )
        raise ExternalServiceError(
            service=self.service,
            operation=operation,
            message="External service circuit is temporarily open",
            endpoint=endpoint,
            category="circuit_open",
            retryable=True,
        )

    def _record_circuit_failure(self) -> None:
        with _CIRCUITS_LOCK:
            state = _CIRCUITS[self._circuit_key]
            state.failures += 1
            if state.failures >= self.circuit_failure_threshold:
                state.opened_at = time.monotonic()

    def _record_circuit_success(self) -> None:
        with _CIRCUITS_LOCK:
            state = _CIRCUITS[self._circuit_key]
            state.failures = 0
            state.opened_at = None

    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        candidate = str(base_url or "").strip()
        parsed = urlsplit(candidate)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("External service base URL must be HTTP(S) without credentials.")
        return candidate.rstrip("/") + "/"

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int | None]:
        parsed = urlsplit(url)
        return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port

    def _validated_url(self, path: str) -> str:
        candidate = str(path or "").strip()
        if not candidate or candidate.startswith("//") or "\\" in candidate:
            endpoint = self._safe_endpoint(candidate)
            self._log_failure(
                event=f"{self.service}.request.unsafe_url_rejected",
                operation="validate_url",
                endpoint=endpoint,
                message="Unsafe external service path rejected",
                category="unsafe_url",
            )
            raise ExternalServiceError(
                service=self.service,
                operation="validate_url",
                message="Unsafe external service path",
                endpoint=endpoint,
                category="unsafe_url",
            )
        parsed = urlsplit(candidate)
        if parsed.scheme or parsed.netloc:
            url = candidate
        else:
            url = urljoin(self.base_url, candidate.lstrip("/"))
        if self._origin(url) != self._origin(self.base_url):
            endpoint = self._safe_endpoint(candidate)
            self._log_failure(
                event=f"{self.service}.request.unsafe_url_rejected",
                operation="validate_url",
                endpoint=endpoint,
                message="Cross-origin external URL rejected",
                category="unsafe_url",
            )
            raise ExternalServiceError(
                service=self.service,
                operation="validate_url",
                message="Cross-origin external URL rejected",
                endpoint=endpoint,
                category="unsafe_url",
            )
        return url

    @staticmethod
    def _safe_endpoint(path: str) -> str:
        parsed = urlsplit(str(path or ""))
        return urlunsplit(("", "", parsed.path, "", ""))[:500] or "/"

    def _log_failure(
        self,
        *,
        event: str,
        operation: str,
        endpoint: str,
        message: str = "External API request failed",
        status_code: int | None = None,
        response_snippet: str | None = None,
        category: str = "external_service_error",
        retryable: bool = False,
    ) -> None:
        self._logger.warning(
            message,
            extra={
                "event": event,
                "external_service": self.service,
                "external_operation": operation,
                "external_endpoint": endpoint,
                "external_status_code": status_code,
                "external_response_snippet": response_snippet,
                "category": category,
                "retryable": retryable,
            },
        )
