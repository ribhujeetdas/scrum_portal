from __future__ import annotations

import re
import logging
from typing import Any
from urllib.parse import urljoin

import requests
from flask import current_app, has_app_context
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


_SECRET_PATTERNS = (
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE), r"\1<redacted>"),
    (re.compile(r"(\bpat[_ -]?(?:secret|token)?\b\s*[=:]\s*)\S+", re.IGNORECASE), r"\1<redacted>"),
    (re.compile(r"(\bpassword\b\s*[=:]\s*)\S+", re.IGNORECASE), r"\1<redacted>"),
    (re.compile(r"(\bcsrf[_ -]?token\b\s*[=:]\s*)\S+", re.IGNORECASE), r"\1<redacted>"),
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
    ):
        self.service = service
        self.operation = operation
        self.message = message
        self.status_code = status_code
        self.response_snippet = response_snippet
        self.endpoint = endpoint
        parts = [f"{service} {operation}: {message}"]
        if status_code is not None:
            parts.append(f"status={status_code}")
        if response_snippet:
            parts.append(f"response={response_snippet}")
        super().__init__("; ".join(parts))


class ExternalHttpClient:
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
        retry_allowed_methods: tuple[str, ...] = ("GET", "POST", "PUT"),
    ):
        self.service = service
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
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
        self._session = session or self._build_session()
        self._logger = logging.getLogger("app.external")

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

        try:
            return response.json()
        except ValueError as exc:
            snippet = str(redact_text(response.text[:500]))
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

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        method = method.upper()
        operation = f"{method} {path}"
        kwargs.setdefault("timeout", self.timeout_seconds)
        url = urljoin(self.base_url, path if path.startswith(("http://", "https://")) else path.lstrip("/"))

        try:
            response = getattr(self._session, method.lower())(url, **kwargs)
        except requests.RequestException as exc:
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
            ) from exc

        if response.status_code >= 400:
            snippet = str(redact_text(response.text[:500]))
            self._log_failure(
                event=f"{self.service}.request.failed",
                operation=operation,
                endpoint=path,
                status_code=response.status_code,
                response_snippet=snippet,
            )
            raise ExternalServiceError(
                service=self.service,
                operation=operation,
                message="HTTP request failed",
                status_code=response.status_code,
                response_snippet=snippet,
                endpoint=path,
            )

        return response

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
