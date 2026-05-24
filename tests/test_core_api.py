from __future__ import annotations

from flask import Flask, g

from app.core.api import json_error, json_ok


def test_json_error_returns_consistent_sanitized_payload():
    app = Flask(__name__)

    @app.before_request
    def set_request_id():
        g.request_id = "api-123"

    @app.route("/fail")
    def fail():
        return json_error(
            "Invalid request",
            status_code=422,
            code="validation_failed",
            details={"field": "project_key", "pat_token": "secret-token"},
        )

    response = app.test_client().get("/fail")

    assert response.status_code == 422
    assert response.json == {
        "ok": False,
        "error": {
            "message": "Invalid request",
            "code": "validation_failed",
            "details": {"field": "project_key", "pat_token": "<redacted>"},
        },
        "request_id": "api-123",
    }


def test_json_ok_includes_request_id_and_payload():
    app = Flask(__name__)

    @app.before_request
    def set_request_id():
        g.request_id = "api-456"

    @app.route("/ok")
    def ok():
        return json_ok(project_key="ABC")

    response = app.test_client().get("/ok")

    assert response.status_code == 200
    assert response.json == {
        "ok": True,
        "project_key": "ABC",
        "request_id": "api-456",
    }
