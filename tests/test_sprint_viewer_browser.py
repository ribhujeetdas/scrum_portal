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
        "total": 2,
        "standard_total": 2,
        "total_sp": 0,
        "sprint": {"name": "Sprint 202", "goal": "Ship safely"},
        "stats": {},
        "work_type_mix": {
            "totals": {"count": 2, "pts": 0, "estimated_count": 2, "unestimated_count": 0},
            "overall": {
                "Story": {"count": 1, "pts": 0, "issue_pct": 50},
                "Defect": {"count": 1, "pts": 0, "issue_pct": 50},
            },
            "by_assignee": [
                {
                    "assignee_eid": "E123",
                    "assignee_name": "Test User",
                    "total_count": 1,
                    "total_pts": 0,
                    "types": {"Story": {"count": 1, "pts": 0}},
                },
                {
                    "assignee_eid": "E456",
                    "assignee_name": "Second User",
                    "total_count": 1,
                    "total_pts": 0,
                    "types": {"Defect": {"count": 1, "pts": 0}},
                },
            ],
        },
        "groups": [
            {
                "principal_id": "key:KEY123",
                "assignee_eid": "E123",
                "assignee_name": "Test User",
                "issue_count": 1,
                "sp_sum": 0,
                "issues": [{
                    "issue_id": "1",
                    "issue_key": "ABC-1",
                    "summary": "Ticket first",
                    "issue_type": "Story",
                    "status": "Done",
                    "story_points": 0,
                    "assignee_eid": "E123",
                    "assignee_name": "Test User",
                    "principal_id": "key:KEY123",
                    "historical_fallback": True,
                }],
            },
            {
                "principal_id": "key:E456",
                "assignee_eid": "E456",
                "assignee_name": "Second User",
                "issue_count": 1,
                "sp_sum": 0,
                "issues": [{
                    "issue_id": "2",
                    "issue_key": "ABC-2",
                    "summary": "Second ticket",
                    "issue_type": "Defect",
                    "status": "In Progress",
                    "story_points": 0,
                    "assignee_eid": "E456",
                    "assignee_name": "Second User",
                    "principal_id": "key:E456",
                    "historical_fallback": False,
                }],
            },
        ],
        "next_cursor": None,
    }
    completed = {
        **core_ready,
        "state": "ready",
        "response_revision": 3,
        "components": {
            "core": {"state": "ready", "revision": 7},
            "history": {"state": "unavailable", "revision": None},
            "comments": {"state": "ready", "revision": 8},
            "metrics": {"state": "ready", "revision": 9},
        },
        "access": {"core": "granted", "metrics": "granted", "history": "unavailable", "comments": "granted"},
    }
    comments_component = {
        "ok": True,
        "data": {
            "issues": {"1": {"comment_total": 2, "relevant_comment_count": 1}},
            "stats": {"relevant_comment_count": 1, "zero_relevant_comment_count": 1, "zero_relevant_comment_pct": 50},
        },
    }
    metrics_component = {"ok": True, "data": {}}
    release_enrichment = {"value": False}

    def fulfill(route):
        url = route.request.url
        method = route.request.method
        headers = {"Content-Type": "application/json"}
        if url.endswith("/api/automation/sprint-viewer/sprints"):
            body = {"ok": True, "sprints": [{"id": 202, "name": "Sprint 202", "state": "closed"}]}
        elif method == "POST" and url.endswith("/api/automation/sprint-viewer/issues"):
            body = pending
        elif "/status?" in url:
            body = completed if release_enrichment["value"] else core_ready
        elif f"/snapshots/{snapshot_id}/issues?" in url:
            body = core_payload
        elif f"/snapshots/{snapshot_id}/components/comments?" in url:
            body = comments_component
        elif f"/snapshots/{snapshot_id}/components/metrics?" in url:
            body = metrics_component
        else:
            body = {"ok": False, "error": {"message": "Unexpected browser fixture request"}}
        route.fulfill(status=200 if body.get("ok") else 500, headers=headers, body=json.dumps(body))

    page.route("**/api/automation/sprint-viewer/**", fulfill)
    page_errors = []
    console_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
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
        assert page.locator("#totalIssues").inner_text() == "2"
        assert page.locator("#fetchIssuesBtn").is_enabled()
        assert page.locator("#fetchIssuesBtn").inner_text().strip() == "Start Over"
        assert page.locator("#committedFmt").inner_text() == "…"
        assert page.locator("#workTypeContent").is_visible()
        assert "Story · 0 pts · —" in page.locator("#workTypePointLegend").text_content()
        assert "Defect · 0 pts · —" in page.locator("#workTypePointLegend").text_content()
        assert page.locator("#workTypeOverallTotal").inner_text().split() == ["Total", "0", "—", "2", "100%"]
        assert "0 pts\n1 issue · — of sprint points" == page.locator(
            "#workTypeByDeveloper .sv-matrix-value:nth-child(2)"
        ).first.inner_text()
        assert page.locator("#estimationCoverageValue").inner_text() == "—"
        assert page.locator("#sprintViewTitle").inner_text() == "Sprint View"
        assert page.locator("#statsBox .sv-health-help").count() == 6
        assert page.locator("#statsBox .sv-health-help").first.evaluate(
            "el => Boolean(window.bootstrap.Tooltip.getInstance(el))"
        )
        assert "Calculating metrics" in page.locator("#sprintViewerProgress").inner_text()
        assert page.locator("#loadingOverlay").get_attribute("aria-hidden") == "true"

        accordion_buttons = page.locator("#assigneeAccordion .accordion-button")
        accordion_buttons.nth(0).click()
        accordion_buttons.nth(1).click()
        page.wait_for_function(
            "document.querySelectorAll('#assigneeAccordion .accordion-collapse.show').length === 2"
        )
        release_enrichment["value"] = True
        page.wait_for_function("document.getElementById('relevantCommentCount').textContent === '1'")
        assert page.locator("#assigneeAccordion .accordion-collapse.show").count() == 2
        page.locator("#assigneeAccordion .accordion-button").nth(0).click()
        page.wait_for_function(
            "document.querySelectorAll('#assigneeAccordion .accordion-collapse.show').length === 1"
        )
        assert page.locator("#assigneeAccordion .accordion-collapse").nth(1).get_attribute("class").endswith("show")
        assert not page_errors
        assert not console_errors

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
