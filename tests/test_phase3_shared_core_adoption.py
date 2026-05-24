from __future__ import annotations

import inspect


def test_external_services_use_shared_http_client_instead_of_local_sessions():
    from app.services.jira_issue_links_service import JiraIssueLinksService
    from app.services.jira_projects_service import JiraProjectsService
    from app.services.rule_copier_service import RuleCopierService
    from app.services.sprint_viewer_service import SprintViewerService
    from app.services.tableau_service import TableauService

    for service_cls in (
        JiraIssueLinksService,
        JiraProjectsService,
        RuleCopierService,
        SprintViewerService,
        TableauService,
    ):
        source = inspect.getsource(service_cls)
        assert "ExternalHttpClient" in source
        assert "requests.Session" not in source
        assert "HTTPAdapter" not in source
        assert "Retry(" not in source


def test_feature_routes_use_shared_dependencies_and_api_helpers():
    import app.features.automation.rule_copier.routes as rule_copier_routes
    import app.features.automation.sprint_viewer.routes as sprint_viewer_routes
    import app.features.reports.tci.routes as tci_routes
    import app.features.settings.projects_boards.routes as projects_boards_routes
    import app.features.settings.tableau_custom_views.routes as tableau_settings_routes

    for module in (
        rule_copier_routes,
        sprint_viewer_routes,
        tci_routes,
        projects_boards_routes,
        tableau_settings_routes,
    ):
        source = inspect.getsource(module)
        assert "from ....core.dependencies import" in source
        assert "def _crypto(" not in source
        assert "def _jira_service(" not in source
        assert "def _tableau_service(" not in source

    for module in (rule_copier_routes, sprint_viewer_routes, tci_routes):
        source = inspect.getsource(module)
        assert "json_error" in source
        assert "json_ok" in source
