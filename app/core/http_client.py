from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import time
from typing import Any, Callable
from urllib.parse import unquote, urljoin, urlparse

import requests
from flask import current_app, has_app_context
from requests.adapters import HTTPAdapter


_SECRET_PATTERNS = (
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE), r"\1<redacted>"),
    (re.compile(r"(\bpat[_ -]?(?:secret|token)?\b\s*[=:]\s*)\S+", re.IGNORECASE), r"\1<redacted>"),
    (re.compile(r"(\bpassword\b\s*[=:]\s*)\S+", re.IGNORECASE), r"\1<redacted>"),
    (re.compile(r"(\bcsrf[_ -]?token\b\s*[=:]\s*)\S+", re.IGNORECASE), r"\1<redacted>"),
    (re.compile(r"(\b(?:cookie|tableau[_ -]?token)\b\s*[=:]\s*)\S+", re.IGNORECASE), r"\1<redacted>"),
)


def redact_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    redacted = value
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


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
        retryable: bool = False,
        outcome: str = "not_sent",
    ):
        self.service = service
        self.operation = operation
        self.message = message
        self.status_code = status_code
        self.response_snippet = response_snippet
        self.endpoint = endpoint
        self.retryable = retryable
        self.outcome = outcome
        parts = [f"{service} {operation}: {message}"]
        if status_code is not None:
            parts.append(f"status={status_code}")
        if response_snippet:
            parts.append(f"response={response_snippet}")
        super().__init__("; ".join(parts))


@dataclass(frozen=True)
class HttpPolicy:
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 20.0
    operation_budget_seconds: float = 60.0
    max_response_bytes: int = 16 * 1024 * 1024
    read_retries: int = 2
    backoff_seconds: float = 0.5
    retry_after_max_seconds: float = 30.0
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)


class ExternalHttpClient:
    """Bounded HTTP client with a single observable retry layer."""

    def __init__(
        self,
        service: str,
        base_url: str,
        *,
        session: requests.Session | None = None,
        timeout_seconds: int = 10,
        retry_total: int | None = None,
        retry_backoff_factor: float | None = None,
        retry_status_forcelist: tuple[int, ...] | None = None,
        retry_allowed_methods: tuple[str, ...] = ("GET", "HEAD"),
        policy: HttpPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        if not str(base_url or "").strip():
            raise ValueError("External service base URL is required")
        self.service = service
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.retry_total = self._config_int("EXTERNAL_HTTP_RETRY_TOTAL", 2, retry_total)
        self.retry_backoff_factor = self._config_float(
            "EXTERNAL_HTTP_RETRY_BACKOFF_SECONDS", 0.5, retry_backoff_factor
        )
        self.retry_status_forcelist = (
            tuple(retry_status_forcelist)
            if retry_status_forcelist is not None
            else self._config_status_codes(
                "EXTERNAL_HTTP_RETRY_STATUS_CODES", (429, 500, 502, 503, 504)
            )
        )
        self.retry_allowed_methods = tuple(method.upper() for method in retry_allowed_methods)
        self.policy = policy or HttpPolicy(
            connect_timeout_seconds=self._config_float("HTTP_CONNECT_TIMEOUT_SECONDS", 5),
            read_timeout_seconds=float(timeout_seconds),
            operation_budget_seconds=self._config_float("HTTP_OPERATION_BUDGET_SECONDS", 60),
            max_response_bytes=self._config_int("HTTP_MAX_JSON_BYTES", 16 * 1024 * 1024),
            read_retries=self.retry_total,
            backoff_seconds=self.retry_backoff_factor,
            retry_after_max_seconds=self._config_float("HTTP_RETRY_AFTER_MAX_SECONDS", 30),
            retry_statuses=self.retry_status_forcelist,
        )
        self._owns_session = session is None
        self._session = session or self._build_session()
        self._sleep = sleep
        self._monotonic = monotonic
        self._logger = logging.getLogger("app.external")

    @staticmethod
    def _config_int(name: str, default: int, explicit: int | None = None) -> int:
        if explicit is not None:
            return int(explicit)
        return int(current_app.config.get(name, default)) if has_app_context() else default

    @staticmethod
    def _config_float(name: str, default: float, explicit: float | None = None) -> float:
        if explicit is not None:
            return float(explicit)
        return float(current_app.config.get(name, default)) if has_app_context() else default

    @staticmethod
    def _config_status_codes(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
        value = current_app.config.get(name, default) if has_app_context() else default
        if isinstance(value, str):
            return tuple(int(part.strip()) for part in value.split(",") if part.strip())
        return tuple(int(part) for part in value)

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        if has_app_context():
            session.trust_env = bool(current_app.config.get("EXTERNAL_TRUST_ENV", True))
            ca_bundle = str(current_app.config.get("EXTERNAL_CA_BUNDLE") or "").strip()
            session.verify = ca_bundle or True
        session.mount("https://", HTTPAdapter(max_retries=0))
        session.mount("http://", HTTPAdapter(max_retries=0))
        return session

    def close(self) -> None:
        if self._owns_session and hasattr(self._session, "close"):
            self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def get_json(self, path: str, **kwargs: Any) -> Any:
        return self._request_json("GET", path, **kwargs)

    def post_json(self, path: str, **kwargs: Any) -> Any:
        return self._request_json("POST", path, **kwargs)

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        kwargs.setdefault("stream", True)
        response = self.request(method, path, **kwargs)
        try:
            if hasattr(response, "iter_content"):
                chunks = []
                received = 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > self.policy.max_response_bytes:
                        raise ExternalServiceError(
                            service=self.service,
                            operation=f"{method} {path}",
                            message="Response exceeded configured size limit",
                            status_code=getattr(response, "status_code", None),
                            endpoint=path,
                        )
                    chunks.append(chunk)
                encoding = getattr(response, "encoding", None) or "utf-8"
                return json.loads(b"".join(chunks).decode(encoding))
            return response.json()
        except (ValueError, UnicodeError) as exc:
            snippet = "<invalid JSON omitted>"
            self._log_failure(
                event=f"{self.service}.response.invalid_json",
                operation=f"{method} {path}",
                endpoint=path,
                status_code=response.status_code,
                response_snippet=snippet,
                message="External API returned invalid JSON",
            )
            raise ExternalServiceError(
                service=self.service,
                operation=f"{method} {path}",
                message="Invalid JSON response",
                status_code=response.status_code,
                response_snippet=snippet,
                endpoint=path,
            ) from exc
        finally:
            if hasattr(response, "close"):
                response.close()

    def _validated_url(self, path: str) -> str:
        base = urlparse(self.base_url)
        candidate = urlparse(path)
        if candidate.scheme or candidate.netloc:
            url = path
        else:
            if path.startswith("//"):
                raise self._url_error("Network-path URLs are not allowed")
            url = urljoin(self.base_url, path.lstrip("/"))
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            raise self._url_error("URL user information is not allowed")

        def origin(parts):
            return (
                parts.scheme.lower(),
                (parts.hostname or "").lower(),
                parts.port or (443 if parts.scheme.lower() == "https" else 80),
            )

        if origin(parsed) != origin(base):
            raise self._url_error("Off-origin URL rejected")
        decoded_path = unquote(parsed.path)
        if any(part == ".." for part in decoded_path.split("/")):
            raise self._url_error("Path traversal rejected")
        base_path = "/" + base.path.strip("/") if base.path.strip("/") else ""
        if base_path and not (decoded_path == base_path or decoded_path.startswith(base_path + "/")):
            raise self._url_error("URL escaped the configured context path")
        return url

    def _url_error(self, message: str) -> ExternalServiceError:
        return ExternalServiceError(
            service=self.service,
            operation="URL validation",
            message=message,
            endpoint="<redacted>",
        )

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        method = method.upper()
        operation = f"{method} {path}"
        url = self._validated_url(path)
        kwargs.setdefault("allow_redirects", False)
        read_safe = method in self.retry_allowed_methods or bool(kwargs.pop("read_safe", False))
        max_attempts = 1 + (self.policy.read_retries if read_safe else 0)
        started = self._monotonic()
        explicit_timeout = kwargs.pop("timeout", None)

        for attempt in range(1, max_attempts + 1):
            remaining = self.policy.operation_budget_seconds - (self._monotonic() - started)
            if remaining <= 0:
                break
            call_kwargs = dict(kwargs)
            if explicit_timeout is None:
                call_kwargs["timeout"] = (
                    min(self.policy.connect_timeout_seconds, remaining),
                    min(self.policy.read_timeout_seconds, remaining),
                )
            else:
                if isinstance(explicit_timeout, tuple):
                    call_kwargs["timeout"] = tuple(min(float(value), remaining) for value in explicit_timeout)
                else:
                    call_kwargs["timeout"] = min(float(explicit_timeout), remaining)
            try:
                response = getattr(self._session, method.lower())(url, **call_kwargs)
            except requests.RequestException as exc:
                if read_safe and attempt < max_attempts:
                    self._bounded_sleep(attempt, remaining)
                    continue
                self._log_failure(
                    event=f"{self.service}.request.failed",
                    operation=operation,
                    endpoint=path,
                    message=str(redact_text(str(exc))),
                )
                raise ExternalServiceError(
                    service=self.service,
                    operation=operation,
                    message=str(redact_text(str(exc))),
                    endpoint=path,
                    retryable=read_safe,
                    outcome="not_sent" if read_safe else "unknown",
                ) from exc

            status = response.status_code
            if 300 <= status < 400:
                self._close_response(response)
                raise ExternalServiceError(
                    service=self.service,
                    operation=operation,
                    message="Unexpected redirect rejected",
                    status_code=status,
                    endpoint=path,
                    outcome="not_sent" if read_safe else "unknown",
                )
            if status < 400:
                return response

            retryable = read_safe and status in self.policy.retry_statuses
            if retryable and attempt < max_attempts:
                headers = getattr(response, "headers", {}) or {}
                try:
                    requested_retry_after = float(headers.get("Retry-After", 0))
                except (TypeError, ValueError):
                    requested_retry_after = 0.0
                self._close_response(response)
                if requested_retry_after > self.policy.retry_after_max_seconds:
                    raise ExternalServiceError(
                        service=self.service,
                        operation=operation,
                        message="Upstream requested deferred retry",
                        status_code=status,
                        endpoint=path,
                        retryable=True,
                        outcome="not_sent",
                    )
                retry_after = max(0.0, requested_retry_after)
                if retry_after:
                    self._sleep(min(retry_after, max(0.0, remaining)))
                else:
                    self._bounded_sleep(attempt, remaining)
                continue

            snippet = self._response_snippet(response)
            self._log_failure(
                event=f"{self.service}.request.failed",
                operation=operation,
                endpoint=path,
                status_code=status,
                response_snippet=snippet,
            )
            self._close_response(response)
            raise ExternalServiceError(
                service=self.service,
                operation=operation,
                message="HTTP request failed",
                status_code=status,
                response_snippet=snippet,
                endpoint=path,
                retryable=retryable,
                outcome="rejected" if status < 500 else ("not_sent" if read_safe else "unknown"),
            )

        raise ExternalServiceError(
            service=self.service,
            operation=operation,
            message="HTTP operation deadline exceeded",
            endpoint=path,
            retryable=read_safe,
            outcome="not_sent" if read_safe else "unknown",
        )

    def _bounded_sleep(self, attempt: int, remaining: float) -> None:
        delay = min(
            self.policy.backoff_seconds * (2 ** (attempt - 1)),
            self.policy.retry_after_max_seconds,
            max(0.0, remaining),
        )
        if delay:
            self._sleep(delay)

    @staticmethod
    def _close_response(response: Any) -> None:
        if hasattr(response, "close"):
            response.close()

    @staticmethod
    def _response_snippet(response: Any) -> str:
        if hasattr(response, "iter_content"):
            chunks = []
            received = 0
            for chunk in response.iter_content(chunk_size=512):
                if not chunk:
                    continue
                take = chunk[: max(0, 500 - received)]
                chunks.append(take)
                received += len(take)
                if received >= 500:
                    break
            raw = b"".join(chunks).decode(getattr(response, "encoding", None) or "utf-8", errors="replace")
        else:
            raw = str(getattr(response, "text", ""))[:500]
        return str(redact_text(raw))

    def _log_failure(
        self,
        *,
        event: str,
        operation: str,
        endpoint: str,
        message: str = "External API request failed",
        status_code: int | None = None,
        response_snippet: str | None = None,
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
            },
        )
