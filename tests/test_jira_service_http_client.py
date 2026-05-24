from __future__ import annotations

import pytest

from app.core.http_client import ExternalServiceError
from app.services.jira_service import JiraService, JiraServiceError


class FakeHttpClient:
    def __init__(self):
        self.calls = []

    def get_json(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return {"accountId": "user-123"}


def test_jira_service_fetch_myself_uses_shared_http_client_when_injected():
    client = FakeHttpClient()
    service = JiraService("https://jira.example", http_client=client)

    result = service.fetch_myself("pat-value")

    assert result == {"accountId": "user-123"}
    assert client.calls == [
        (
            "/rest/api/2/myself",
            {
                "headers": {
                    "Authorization": "Bearer pat-value",
                    "Accept": "application/json",
                }
            },
        )
    ]


class RaisingHttpClient:
    def __init__(self, error):
        self.error = error

    def get_json(self, path, **kwargs):
        raise self.error


def test_jira_service_preserves_invalid_json_error_message():
    service = JiraService(
        "https://jira.example",
        http_client=RaisingHttpClient(
            ExternalServiceError(
                service="jira",
                operation="GET /rest/api/2/myself",
                message="Invalid JSON response",
                status_code=200,
            )
        ),
    )

    with pytest.raises(JiraServiceError, match="Invalid JSON from Jira."):
        service.fetch_myself("pat-value")
