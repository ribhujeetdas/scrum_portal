from __future__ import annotations

import logging

import pytest
import requests

from app.core.http_client import ExternalHttpClient, ExternalServiceError


class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if self.exc:
            raise self.exc
        return self.response

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if self.exc:
            raise self.exc
        return self.response


def test_http_client_get_json_joins_url_and_uses_timeout():
    session = FakeSession(response=FakeResponse(payload={"accountId": "abc"}))
    client = ExternalHttpClient(
        "jira", "https://jira.example", session=session, timeout_seconds=7
    )

    payload = client.get_json(
        "/rest/api/2/myself", headers={"Authorization": "Bearer secret-token"}
    )

    assert payload == {"accountId": "abc"}
    assert session.calls == [
        (
            "GET",
            "https://jira.example/rest/api/2/myself",
            {"headers": {"Authorization": "Bearer secret-token"}, "timeout": 7},
        )
    ]


def test_http_client_http_error_redacts_secret_snippets():
    session = FakeSession(
        response=FakeResponse(
            status_code=500,
            text="Authorization: Bearer secret-token pat_token=abc123 failed",
        )
    )
    client = ExternalHttpClient("jira", "https://jira.example", session=session)

    with pytest.raises(ExternalServiceError) as raised:
        client.get_json("/broken")

    err = raised.value
    assert err.service == "jira"
    assert err.operation == "GET /broken"
    assert err.status_code == 500
    assert "secret-token" not in str(err)
    assert "abc123" not in str(err)
    assert "<redacted>" in err.response_snippet


def test_http_client_network_error_preserves_original_exception():
    original = requests.Timeout("connect timed out")
    session = FakeSession(exc=original)
    client = ExternalHttpClient("jira", "https://jira.example", session=session)

    with pytest.raises(ExternalServiceError) as raised:
        client.post_json("/endpoint", json={"name": "rule"})

    assert raised.value.__cause__ is original
    assert raised.value.service == "jira"
    assert raised.value.operation == "POST /endpoint"
    assert raised.value.status_code is None


def test_http_client_logs_external_api_failure_metadata():
    session = FakeSession(
        response=FakeResponse(
            status_code=503,
            text="pat_secret=super-secret upstream outage",
        )
    )
    client = ExternalHttpClient("tableau", "https://tableau.example", session=session)
    logger = logging.getLogger("app.external")
    handler = ListHandler()
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)

    try:
        with pytest.raises(ExternalServiceError):
            client.get_json("/sites/site-1/customviews")
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)

    record = next(
        record for record in handler.records if record.event == "tableau.request.failed"
    )
    assert record.external_service == "tableau"
    assert record.external_operation == "GET /sites/site-1/customviews"
    assert record.external_endpoint == "/sites/site-1/customviews"
    assert record.external_status_code == 503
    assert "super-secret" not in record.external_response_snippet
    assert "<redacted>" in record.external_response_snippet


def test_http_client_retry_policy_is_configurable():
    client = ExternalHttpClient(
        "jira",
        "https://jira.example",
        retry_total=5,
        retry_backoff_factor=0.25,
        retry_status_forcelist=(500, 503),
    )

    retry = client._session.get_adapter("https://").max_retries

    assert retry.total == 5
    assert retry.backoff_factor == 0.25
    assert retry.status_forcelist == (500, 503)
