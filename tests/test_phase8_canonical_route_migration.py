from __future__ import annotations

from pathlib import Path

from tests.test_phase6_feature_routes_and_failures import (
    add_custom_view,
    add_project,
    create_phase6_app,
    login,
    set_user_tokens,
)


ROOT = Path(__file__).resolve().parents[1]


def test_unauthenticated_canonical_route_redirects_to_canonical_login(tmp_path):
    app = create_phase6_app(tmp_path)

    response = app.test_client().get("/dashboard", follow_redirects=False)

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_dashboard_and_sidebar_render_canonical_links(tmp_path):
    app = create_phase6_app(tmp_path)
    with app.app_context():
        set_user_tokens(tableau_pat=True)
        add_project()
        add_custom_view()

    client = app.test_client()
    login(client)

    response = client.get("/dashboard")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="/dashboard"' in html
    assert 'href="/settings/integrations"' in html
    assert 'href="/reports/tci"' in html
    assert 'action="/auth/logout"' in html
    assert 'href="/home"' not in html
    assert 'href="/config/integrations"' not in html
    assert 'href="/tableau/custom-views"' not in html


def test_settings_tabs_render_canonical_links(tmp_path):
    app = create_phase6_app(tmp_path)
    client = app.test_client()
    login(client)

    response = client.get("/settings/projects-boards")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="/settings/integrations"' in html
    assert 'href="/settings/projects-boards"' in html
    assert 'href="/settings/tableau-custom-views"' in html
    assert 'href="/config/' not in html


def test_frontend_javascript_uses_canonical_api_and_auth_routes():
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            ROOT / "app/static/js/app.js",
            ROOT / "app/static/js/rule_copier.js",
            ROOT / "app/static/js/sprint_viewer.js",
            ROOT / "app/static/js/tci_custom_views.js",
        ]
    )

    assert "/api/client-log" in combined
    assert "/api/session/status" in combined
    assert "/api/session/extend" in combined
    assert "/auth/login" in combined

    for legacy_path in (
        '"/client-log',
        '"/session/status',
        '"/session/extend',
        '"/login"',
        '"/tableau/custom-views/link-details',
    ):
        assert legacy_path not in combined


def test_legacy_routes_remain_available_temporarily(tmp_path):
    app = create_phase6_app(tmp_path)
    rules = {rule.rule for rule in app.url_map.iter_rules()}

    assert "/home" in rules
    assert "/login" in rules
    assert "/config/projects" in rules
    assert "/tableau/custom-views" in rules


def test_legacy_routes_emit_deprecation_headers(tmp_path):
    app = create_phase6_app(tmp_path)
    client = app.test_client()
    login(client)

    response = client.get("/home", follow_redirects=False)

    assert response.status_code == 200
    assert response.headers["Deprecation"] == "true"
    assert "/dashboard" in response.headers["Link"]
