from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any


class JiraPaginationError(ValueError):
    """Raised when Jira cannot prove a complete, progressive page scan."""


@dataclass(frozen=True)
class JiraPage:
    items: list[dict[str, Any]]
    start_at: int
    max_results: int | None
    total: int | None
    is_last: bool | None


def _integer(value: Any, name: str, *, optional: bool = True) -> int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise JiraPaginationError(f"Invalid Jira pagination field: {name}")
    return value


def parse_offset_page(
    payload: Any,
    *,
    collection_key: str,
    requested_start: int,
) -> JiraPage:
    if not isinstance(payload, Mapping):
        raise JiraPaginationError("Jira page must be an object")
    items = payload.get(collection_key)
    if not isinstance(items, list) or any(not isinstance(item, Mapping) for item in items):
        raise JiraPaginationError(f"Jira field {collection_key} must be an array of objects")
    start_at = _integer(payload.get("startAt", requested_start), "startAt", optional=False)
    if start_at != requested_start:
        raise JiraPaginationError("Jira returned a non-matching page offset")
    max_results = _integer(payload.get("maxResults"), "maxResults")
    total = _integer(payload.get("total"), "total")
    raw_last = payload.get("isLast")
    if raw_last is not None and not isinstance(raw_last, bool):
        raise JiraPaginationError("Invalid Jira pagination field: isLast")
    return JiraPage(
        items=[dict(item) for item in items],
        start_at=start_at,
        max_results=max_results,
        total=total,
        is_last=raw_last,
    )


def collect_offset_pages(
    fetch_page: Callable[[int, int], Any],
    *,
    collection_key: str,
    requested_page_size: int,
    identity: Callable[[dict[str, Any]], str | None],
    max_pages: int = 10_000,
    max_items: int = 100_000,
) -> list[dict[str, Any]]:
    """Collect a complete Jira offset sequence and deduplicate stable IDs.

    The requested page size is only a hint. Progress always uses the number of
    records actually returned by Jira. Conflicting duplicates and contradictory
    page metadata fail instead of publishing a partial result.
    """
    if requested_page_size <= 0 or max_pages <= 0 or max_items <= 0:
        raise ValueError("Pagination limits must be positive")

    start_at = 0
    pages = 0
    result: list[dict[str, Any]] = []
    by_id: dict[str, str] = {}
    advertised_total: int | None = None
    consumed_total = 0

    while True:
        if pages >= max_pages:
            raise JiraPaginationError("Jira page limit exceeded")
        page = parse_offset_page(
            fetch_page(start_at, requested_page_size),
            collection_key=collection_key,
            requested_start=start_at,
        )
        pages += 1
        if page.total is not None:
            if advertised_total is not None and advertised_total != page.total:
                raise JiraPaginationError("Jira total changed during pagination")
            advertised_total = page.total

        for item in page.items:
            stable_id = identity(item)
            if stable_id is None or not str(stable_id).strip():
                raise JiraPaginationError("Jira item is missing a stable ID")
            stable_id = str(stable_id).strip()
            encoded = json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)
            previous = by_id.get(stable_id)
            if previous is not None and previous != encoded:
                raise JiraPaginationError("Jira returned conflicting duplicate records")
            if previous is None:
                by_id[stable_id] = encoded
                result.append(item)
                if len(result) > max_items:
                    raise JiraPaginationError("Jira item limit exceeded")

        consumed = len(page.items)
        next_start = start_at + consumed
        consumed_total = next_start
        reached_total = advertised_total is not None and next_start >= advertised_total

        if page.is_last is True:
            if advertised_total is not None and next_start < advertised_total:
                raise JiraPaginationError("Jira ended pagination before the advertised total")
            break
        if page.is_last is False and consumed == 0:
            raise JiraPaginationError("Jira returned an empty non-final page")
        if reached_total:
            break
        if consumed == 0:
            if advertised_total in (None, 0):
                break
            raise JiraPaginationError("Jira returned an empty page before completion")

        start_at = next_start

    if advertised_total is not None and consumed_total < advertised_total:
        raise JiraPaginationError("Jira pagination did not reach the advertised total")
    return result
