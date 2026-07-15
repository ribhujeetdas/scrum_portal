from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

SECRET_KEY_FRAGMENTS = (
    "authorization",
    "csrf",
    "password",
    "pat",
    "secret",
    "token",
)

_SECRET_PATTERNS = (
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE), r"\1<redacted>"),
    (
        re.compile(
            r"((?:[\"']?(?:authorization|access[_-]?token|refresh[_-]?token|"
            r"csrf[_ -]?token|pat[_ -]?(?:secret|token)?|password|secret)[\"']?"
            r"\s*[:=]\s*[\"']?))([^\"'\s,;}&]+)",
            re.IGNORECASE,
        ),
        r"\1<redacted>",
    ),
)


def redact(value: Any) -> Any:
    """Recursively redact secret-bearing keys and common secret text formats."""
    if value is None:
        return None
    if isinstance(value, Mapping):
        mapping_output = {}
        for key, item in value.items():
            key_text = str(key).lower()
            mapping_output[key] = (
                "<redacted>"
                if any(fragment in key_text for fragment in SECRET_KEY_FRAGMENTS)
                else redact(item)
            )
        return mapping_output
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    text_output = value
    for pattern, replacement in _SECRET_PATTERNS:
        text_output = pattern.sub(replacement, text_output)
    return text_output
