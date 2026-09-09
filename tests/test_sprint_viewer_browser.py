from __future__ import annotations

import json
import threading

from cryptography.fernet import Fernet
from openpyxl import load_workbook
from werkzeug.serving import make_server

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User, UserBoard, UserProject


def test_core_tickets_are_interactive_while_metrics_are_still_running(page, tmp_path):
    database_path = tmp_path / "browser.db"

    class BrowserConfig(Config):
        TESTING = True
        SECRET_KEY = "browser-test-secret"
        WTF_CSRF_ENABLED = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path.as_posix()}"
        FERNET_KEY = Fernet.generate_key().decode("ascii")
        JIRA_BASE_URL = "https://jira.example"
        SPRINT_VIEWER_MODE = "snapshot"
        LOG_TO_CONSOLE = False
        LOG_LEVEL = "WARNING"
        LOG_SQLALCHEMY_LEVEL = "WARNING"
        LOG_WERKZEUG_LEVEL = "WARNING"
        LOG_DIR = str(tmp_path / "logs")

    app = create_app(BrowserConfig)
    with app.app_context():
        db.create_all()
        user = User(
            eid="E123",
            jira_key="KEY123",
            email="user@example.com",
            display_name="Test User",
            password_hash="placeholder",
        )
        user.set_password("Password12345")
        db.session.add(user)
        db.session.flush()
        project = UserProject(user_id=user.id, project_key="ABC", admin_projects=True)
        db.session.add(project)
        db.session.flush()
        db.session.add(UserBoard(
            project_id=project.id,
            board_id=101,
            board_name="Team Board",
            board_type="scrum",
        ))
        db.session.commit()

    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    snapshot_id = "11111111-1111-4111-8111-111111111111"
    view_id = "22222222-2222-4222-8222-222222222222"

    pending = {
        "ok": True,
        "state": "processing",
        "snapshot_id": snapshot_id,
        "view_id": view_id,
        "generation": 1,
        "response_revision": 1,
        "components": {"core": {"state": "queued", "revision": None}},
        "access": {"core": "pending", "metrics": "pending"},
        "export_ready": False,
    }
    core_ready = {
        **pending,
        "response_revision": 2,
        "components": {
            "core": {"state": "ready", "revision": 7},
            "history": {"state": "running", "revision": None},
            "comments": {"state": "running", "revision": None},
            "metrics": {"state": "running", "revision": None},
        },
        "access": {"core": "granted", "metrics": "pending", "history": "pending", "comments": "pending"},
    }
    core_payload = {
        "ok": True,
        "total": 1,
        "standard_total": 1,
        "total_sp": 5,
        "sprint": {"name": "Sprint 202", "goal": "Ship safely"},
        "stats": {},
        "work_type_mix": {"overall": {}, "by_assignee": []},
        "groups": [{
            "principal_id": "key:KEY123",
            "assignee_eid": "E123",
            "assignee_name": "Test User",
            "issue_count": 1,
            "sp_sum": 5,
            "issues": [{
                "issue_id": "1",
                "issue_key": "ABC-1",
                "summary": "Ticket first",
                "issue_type": "Story",
                "status": "Done",
                "story_points": 5,
                "assignee_eid": "E123",
                "assignee_name": "Test User",
                "principal_id": "key:KEY123",
                "historical_fallback": True,
            }],
        }],
        "next_cursor": None,
    }

    def fulfill(route):
        url = route.request.url
        method = route.request.method
        headers = {"Content-Type": "application/json"}
        if url.endswith("/api/automation/sprint-viewer/sprints"):
            body = {"ok": True, "sprints": [{"id": 202, "name": "Sprint 202", "state": "closed"}]}
        elif method == "POST" and url.endswith("/api/automation/sprint-viewer/issues"):
            body = pending
        elif "/status?" in url:
            body = core_ready
        elif f"/snapshots/{snapshot_id}/issues?" in url:
            body = core_payload
        else:
            body = {"ok": False, "error": {"message": "Unexpected browser fixture request"}}
        route.fulfill(status=200 if body.get("ok") else 500, headers=headers, body=json.dumps(body))

    page.route("**/api/automation/sprint-viewer/**", fulfill)
    try:
        page.goto(f"{origin}/auth/login")
        page.locator('input[name="identifier"]').fill("user@example.com")
        page.locator('input[name="password"]').fill("Password12345")
        page.locator('button[type="submit"], input[type="submit"]').first.click()
        page.goto(f"{origin}/automation/sprint-viewer")
        page.wait_for_function(
            "document.getElementById('sprintViewerPage')?.dataset.sprintViewerInitialized === 'true'"
        )
        page.select_option("#projectKey", "ABC")
        page.select_option("#boardId", "101")
        page.locator("#sprintId option[value='202']").wait_for(state="attached")
        page.select_option("#sprintId", "202")
        page.locator("#fetchIssuesBtn").click()

        page.locator("#totalIssues").wait_for(state="visible")
        assert page.locator("#totalIssues").inner_text() == "1"
        assert page.locator("#fetchIssuesBtn").is_enabled()
        assert page.locator("#fetchIssuesBtn").inner_text().strip() == "Start Over"
        assert page.locator("#committedFmt").inner_text() == "…"
        assert "Calculating metrics" in page.locator("#sprintViewerProgress").inner_text()
        assert page.locator("#loadingOverlay").get_attribute("aria-hidden") == "true"

        workbook_bytes = page.evaluate("""async () => {
          const module = await import('/static/js/sprint_viewer/export.js');
          return Array.from(module.buildWorkbookBytes({
            manifest: { snapshot_id: 's1', generation: 1, access_checked_at: 'now', time_basis: {} },
            selection: { projectKey: 'ABC', boardName: 'Board', boardId: 101, sprintName: 'Sprint', sprintId: 202 },
            core: { sprint: {}, stats: {}, total: 1, standard_total: 1, total_sp: 5 },
            metrics: {},
            issues: [{ assignee_name: 'User', assignee_eid: 'E1', issue_key: 'ABC-1', summary: '=2+2', issue_type: 'Story', status: 'Done', story_points: 5 }]
          }));
        }""")
        workbook_path = tmp_path / "safe-export.xlsx"
        workbook_path.write_bytes(bytes(workbook_bytes))
        workbook = load_workbook(workbook_path, read_only=True, data_only=False)
        summary_cell = workbook["Ticket Details"]["D2"]
        assert summary_cell.value == "=2+2"
        assert summary_cell.data_type == "s"
        workbook.close()
    finally:
        page.goto("about:blank")
        server.shutdown()
        thread.join(timeout=5)
