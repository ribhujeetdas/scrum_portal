"""
scripts/smoke_check.py

Lightweight smoke check for the Flask app.
Run from repo root:
    python scripts/smoke_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path


# --- Ensure repo root is on sys.path -----------------------------------------
# When running "python scripts/smoke_check.py", Python's import base becomes
# the scripts/ folder. Add the repo root so "import app" works reliably.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
# -----------------------------------------------------------------------------


def fail(msg: str) -> None:
    print(f"SMOKE_FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    # Fail fast if app cannot be imported or created
    try:
        from app import create_app
    except Exception as e:
        fail(f"Failed to import create_app(): {e}")

    try:
        app = create_app()
    except Exception as e:
        fail(f"Failed to create Flask app: {e}")

    app.config["TESTING"] = True
    client = app.test_client()

    # 1. Public route – should load
    r = client.get("/login")
    if r.status_code != 200:
        fail(f"GET /login expected 200, got {r.status_code}")

    # 2. Protected routes – should redirect to login
    protected_routes = [
        "/home",
        "/config/integrations",
        "/automation/sprint-viewer",
    ]

    for path in protected_routes:
        r = client.get(path, follow_redirects=False)
        if r.status_code not in (302, 401):
            fail(f"GET {path} expected 302/401, got {r.status_code}")

        if r.status_code == 302:
            loc = r.headers.get("Location", "")
            if "/login" not in loc:
                fail(f"GET {path} redirected to unexpected location: {loc}")

    print("SMOKE_OK")


if __name__ == "__main__":
    main()
