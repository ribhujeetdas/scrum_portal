from __future__ import annotations

import re
from typing import Any


MAX_JIRA_NUMERIC_ID = 9_223_372_036_854_775_807
_DECIMAL_ID = re.compile(r"^[1-9][0-9]*$")


class InputValidationError(ValueError):
    pass


def require_json_object(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InputValidationError("JSON request body must be an object.")
    return payload


def positive_jira_id(value: Any, label: str) -> int:
    if isinstance(value, bool) or isinstance(value, float):
        raise InputValidationError(f"{label} must be a positive integer.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and _DECIMAL_ID.fullmatch(value.strip()):
        parsed = int(value.strip())
    else:
        raise InputValidationError(f"{label} must be a positive integer.")
    if parsed <= 0 or parsed > MAX_JIRA_NUMERIC_ID:
        raise InputValidationError(f"{label} must be a positive integer.")
    return parsed


def strict_boolean(value: Any, label: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise InputValidationError(f"{label} must be a boolean.")
    return value
