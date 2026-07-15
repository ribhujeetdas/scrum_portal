from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from flask import Flask, current_app, request


@dataclass(frozen=True)
class RateLimitExceeded(Exception):
    scope: str
    retry_after: int

    def __str__(self) -> str:
        return f"Rate limit exceeded for {self.scope}; retry in {self.retry_after} seconds."


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, *, scope: str, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        oldest = now - window_seconds
        bucket_key = (scope, key)
        with self._lock:
            bucket = self._events[bucket_key]
            while bucket and bucket[0] <= oldest:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])) + 1)
                raise RateLimitExceeded(scope, retry_after)
            bucket.append(now)
            if len(self._events) > 10000:
                self._prune(now)

    def reset(self, *, scope: str, key: str) -> None:
        with self._lock:
            self._events.pop((scope, key), None)

    def _prune(self, now: float) -> None:
        empty = []
        for key, bucket in self._events.items():
            while bucket and bucket[0] <= now - 86400:
                bucket.popleft()
            if not bucket:
                empty.append(key)
        for key in empty:
            self._events.pop(key, None)


def init_rate_limiter(app: Flask) -> None:
    app.extensions["portal_rate_limiter"] = InMemoryRateLimiter()


def _limiter() -> InMemoryRateLimiter:
    return current_app.extensions["portal_rate_limiter"]


def subject_hash(value: str) -> str:
    normalized = value.strip().lower().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()[:20]


def request_source() -> str:
    return str(request.remote_addr or "unknown")[:64]


def enforce_limit(
    scope: str,
    *,
    subject: str = "",
    limit: int | None = None,
    window_seconds: int | None = None,
    expensive: bool = False,
) -> str:
    key = f"{request_source()}:{subject_hash(subject) if subject else '-'}"
    if not current_app.config.get("RATE_LIMIT_ENABLED", True):
        return key
    prefix = "EXPENSIVE" if expensive else "LOGIN"
    selected_limit = int(
        limit if limit is not None else current_app.config.get(f"RATE_LIMIT_{prefix}_ATTEMPTS", 20)
    )
    selected_window = int(
        window_seconds
        if window_seconds is not None
        else current_app.config.get(f"RATE_LIMIT_{prefix}_WINDOW_SECONDS", 60)
    )
    _limiter().check(
        scope=scope,
        key=key,
        limit=selected_limit,
        window_seconds=selected_window,
    )
    return key


def reset_limit(scope: str, key: str) -> None:
    _limiter().reset(scope=scope, key=key)
