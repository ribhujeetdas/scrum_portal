from __future__ import annotations

import pytest

from app.core.redaction import redact


@pytest.mark.parametrize(
    "value",
    [
        "Authorization: Bearer secret-token",
        'response={"access_token":"secret-token"}',
        "password=hunter2; request failed",
        "pat_secret=secret-token upstream outage",
    ],
)
def test_redact_removes_common_secret_text_formats(value):
    redacted = redact(value)

    assert "secret-token" not in redacted
    assert "hunter2" not in redacted
    assert "<redacted>" in redacted


def test_redact_recursively_filters_secret_bearing_mapping_keys():
    payload = {
        "safe": "visible",
        "nested": [
            {"csrf_token": "csrf-secret", "count": 2},
            {"credentials": {"jira_pat": "pat-secret"}},
        ],
    }

    assert redact(payload) == {
        "safe": "visible",
        "nested": [
            {"csrf_token": "<redacted>", "count": 2},
            {"credentials": {"jira_pat": "<redacted>"}},
        ],
    }
