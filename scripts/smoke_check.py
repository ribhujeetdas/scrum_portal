"""
scripts/smoke_check.py

Lightweight smoke check for the Flask app.
Run from repo root:
    python scripts/smoke_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def fail(msg: str) -> None:
    print(f"SMOKE_FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    try:
        from app import create_app
    except Exception as exc:
        fail(f"Failed to import create_app(): {exc}")

    try:
        app = create_app()
    except Exception as exc:
        fail(f"Failed to create Flask app: {exc}")

    app.config["TESTING"] = True
    client = app.test_client()

    for path in ("/auth/login", "/login"):
        response = client.get(path)
        if response.status_code != 200:
            fail(f"GET {path} expected 200, got {response.status_code}")

    protected_routes = [
        "/dashboard",
        "/settings/integrations",
        "/automation/sprint-viewer",
        "/reports/tci",
    ]
    for path in protected_routes:
        response = client.get(path, follow_redirects=False)
        if response.status_code not in (302, 401):
            fail(f"GET {path} expected 302/401, got {response.status_code}")
        if response.status_code == 302:
            location = response.headers.get("Location", "")
            if "/auth/login" not in location:
                fail(f"GET {path} redirected to unexpected location: {location}")

    legacy_routes = ["/home", "/config/integrations", "/tableau/custom-views"]
    for path in legacy_routes:
        response = client.get(path, follow_redirects=False)
        if response.status_code not in (302, 401):
            fail(f"GET legacy {path} expected 302/401, got {response.status_code}")

    print("SMOKE_OK")


if __name__ == "__main__":
    main()
