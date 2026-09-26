from __future__ import annotations

import json
import threading

from cryptography.fernet import Fernet
from werkzeug.serving import make_server

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User, UserBoard, UserProject


def test_rule_copier_loads_and_copies_data_center_rule_end_to_end(page, tmp_path):
    database_path = tmp_path / "rule-copier-browser.db"

    class BrowserConfig(Config):
        TESTING = True
        SECRET_KEY = "browser-test-secret"
        WTF_CSRF_ENABLED = False
        SESSION_COOKIE_SECURE = False
        REMEMBER_COOKIE_SECURE = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{database_path.as_posix()}"
        FERNET_KEY = Fernet.generate_key().decode("ascii")
        JIRA_BASE_URL = "https://jira.example"
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
        project = UserProject(
            user_id=user.id,
            project_key="ABC",
            admin_projects=True,
            project_id=12345,
        )
        db.session.add(project)
        db.session.flush()
        db.session.add(
            UserBoard(
                project_id=project.id,
                board_id=101,
                board_name="Team Board",
                board_type="scrum",
            )
        )
        db.session.commit()

    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    rule_requests = {"count": 0}

    def fulfill(route):
        url = route.request.url
        if url.endswith("/api/automation/rule-copier/rules"):
            rule_requests["count"] += 1
            rules = [
                {"id": 101, "name": "Assign default reviewer", "state": "ENABLED"},
                {"id": 202, "name": "Deploy readiness checks", "state": "DISABLED"},
                {"id": 303, "name": "Notify feature owner", "state": "ENABLED"},
            ]
            if rule_requests["count"] > 1:
                rules.append({"id": 404, "name": "Refreshed rule", "state": "ENABLED"})
            body = {
                "ok": True,
                "rules": rules,
            }
        elif url.endswith("/api/automation/rule-copier/fetch"):
            request = route.request.post_data_json
            assert request["rule_id"] == "202"
            body = {
                "ok": True,
                "rule": {"id": 202, "name": "Deploy readiness checks", "state": "DISABLED"},
                "sanitization": {
                    "redacted_count": 2,
                    "redacted_header_names": ["Authorization", "X-API-Key"],
                    "redacted_field_names": [],
                    "source_secret_names": ["jira_token"],
                },
            }
        elif url.endswith("/api/automation/rule-copier/copy"):
            request = route.request.post_data_json
            assert request["target_project_key"] == "ABC"
            assert request["target_board_id"] == 101
            assert request["source_project_key"] == "ABC"
            assert request["source_board_id"] == 101
            assert request["source_rule_id"] == 202
            assert "rule_json" not in request
            body = {
                "ok": True,
                "message": (
                    "Rule copied successfully with placeholder values for 2 sensitive entries. "
                    "Replace the placeholders in the destination rule before enabling it."
                ),
            }
        else:
            body = {"ok": False, "error": {"message": "Unexpected browser fixture request"}}
        route.fulfill(
            status=200 if body.get("ok") else 409,
            headers={"Content-Type": "application/json"},
            body=json.dumps(body),
        )

    page.route("**/api/automation/rule-copier/**", fulfill)
    page_errors = []
    console_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )

    try:
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.goto(f"{origin}/auth/login")
        page.locator('input[name="identifier"]').fill("user@example.com")
        page.locator('input[name="password"]').fill("Password12345")
        page.locator('button[type="submit"], input[type="submit"]').first.click()
        page.goto(f"{origin}/automation/rule-copier")

        assert page.title() == "Jira Automation Rule Copier"
        page.locator('script[src*="rule_copier.js"]').wait_for(state="attached")
        page.select_option("#srcProject", "ABC")
        page.locator("#srcBoard option[value='101']").wait_for(state="attached")
        page.select_option("#srcBoard", "101")

        page.wait_for_function(
            "document.querySelectorAll('#sourceRule option').length === 4"
        )
        assert page.locator("#sourceRule option").all_inner_texts()[1:] == [
            "101 — Assign default reviewer (ENABLED)",
            "202 — Deploy readiness checks (DISABLED)",
            "303 — Notify feature owner (ENABLED)",
        ]
        assert page.locator("#ruleSearch").count() == 0
        control_tops = page.locator(
            "#srcProject, #srcBoard, #sourceRule, #refreshRulesBtn, #fetchRuleBtn"
        ).evaluate_all("elements => elements.map(element => element.getBoundingClientRect().top)")
        assert max(control_tops) - min(control_tops) <= 1
        assert page.locator("#refreshRulesBtn").is_enabled()

        page.locator("#refreshRulesBtn").click()
        page.wait_for_function(
            "document.querySelectorAll('#sourceRule option').length === 5"
        )
        assert page.locator("#sourceRule option").all_inner_texts()[-1] == (
            "404 — Refreshed rule (ENABLED)"
        )

        page.select_option("#sourceRule", "202")
        assert page.locator("#fetchRuleBtn").is_enabled()
        page.locator("#fetchRuleBtn").click()

        page.locator("#ruleDetailsCard").wait_for(state="visible")
        assert page.locator("#outRuleId").inner_text() == "202"
        assert page.locator("#outRuleName").inner_text() == "Deploy readiness checks"
        assert page.locator("#outRuleState").inner_text() == "DISABLED"
        assert page.locator("#ruleSecurityNotice").inner_text() == (
            "2 sensitive entries (Authorization, X-API-Key) will be copied with placeholder "
            "values. Replace the placeholders with destination-specific credentials before "
            "enabling the rule."
        )
        assert "literal-secret" not in page.locator("body").inner_text()
        assert page.locator("#confirmBtn").is_enabled()

        page.locator("#confirmBtn").click()
        page.locator("#step2").wait_for(state="visible")
        page.select_option("#dstProject", "ABC")
        page.locator("#dstBoard option[value='101']").wait_for(state="attached")
        assert page.locator("#dstBoard").is_enabled()
        page.select_option("#dstBoard", "101")
        assert page.locator("#copyRuleBtn").is_enabled()
        page.locator("#copyRuleBtn").click()
        page.get_by_text(
            "Rule copied successfully with placeholder values for 2 sensitive entries. Replace the placeholders in the destination rule before enabling it."
        ).wait_for(state="visible")

        assert not page_errors
        assert not console_errors

        page.screenshot(path=tmp_path / "rule-copier-desktop.png", full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=tmp_path / "rule-copier-mobile.png", full_page=True)
        overflowing = page.evaluate(
            """() => Array.from(document.querySelectorAll('*'))
              .map(element => {
                const rect = element.getBoundingClientRect();
                return {
                  tag: element.tagName,
                  id: element.id,
                  left: rect.left,
                  right: rect.right,
                  width: rect.width,
                  scrollWidth: element.scrollWidth,
                  clientWidth: element.clientWidth
                };
              })
              .filter(item => item.right > document.documentElement.clientWidth + 0.5 || item.left < -0.5)"""
        )
        assert page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
        ), overflowing
    finally:
        page.goto("about:blank")
        server.shutdown()
        thread.join(timeout=5)
