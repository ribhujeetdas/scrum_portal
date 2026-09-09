from __future__ import annotations

from flask import current_app, g

from app.services.crypto_service import CryptoService
from app.services.jira_issue_links_service import JiraIssueLinksService
from app.services.jira_projects_service import JiraProjectsService
from app.services.jira_service import JiraService
from app.services.rule_copier_service import RuleCopierService
from app.services.sprint_viewer_service import SprintViewerService
from app.services.tableau_service import TableauService


def _memoized(name: str, factory):
    services = g.setdefault("request_services", {})
    if name not in services:
        services[name] = factory()
    return services[name]


def close_request_services(_error=None) -> None:
    for service in g.pop("request_services", {}).values():
        client = getattr(service, "_client", None)
        if client and hasattr(client, "close"):
            client.close()


def crypto_service() -> CryptoService:
    return _memoized("crypto", lambda: CryptoService(current_app.config["FERNET_KEY"]))


def jira_service() -> JiraService:
    return _memoized("jira", lambda: JiraService(
        current_app.config["JIRA_BASE_URL"],
        timeout_seconds=current_app.config.get("EXTERNAL_HTTP_TIMEOUT_SECONDS", 20),
    ))


def jira_projects_service() -> JiraProjectsService:
    return _memoized("jira_projects", lambda: JiraProjectsService(
        current_app.config["JIRA_BASE_URL"],
        timeout_seconds=current_app.config.get("EXTERNAL_HTTP_TIMEOUT_SECONDS", 20),
    ))


def jira_issue_links_service() -> JiraIssueLinksService:
    return _memoized("jira_issue_links", lambda: JiraIssueLinksService(
        current_app.config.get("JIRA_BASE_URL", ""),
        timeout_seconds=current_app.config.get("EXTERNAL_HTTP_TIMEOUT_SECONDS", 20),
    ))


def rule_copier_service() -> RuleCopierService:
    return _memoized("rule_copier", lambda: RuleCopierService(
        current_app.config["JIRA_BASE_URL"],
        timeout_seconds=current_app.config.get("EXTERNAL_HTTP_TIMEOUT_SECONDS", 30),
    ))


def sprint_viewer_service() -> SprintViewerService:
    return _memoized("sprint_viewer", lambda: SprintViewerService(
        current_app.config["JIRA_BASE_URL"],
        timeout_seconds=current_app.config.get(
            "SPRINT_METRICS_HTTP_TIMEOUT_SECONDS",
            current_app.config.get("EXTERNAL_HTTP_TIMEOUT_SECONDS", 30),
        ),
        metrics_max_workers=current_app.config.get("SPRINT_METRICS_MAX_WORKERS", 5),
        story_points_field=current_app.config.get("JIRA_STORY_POINTS_FIELD", "customfield_10106"),
        application_field=current_app.config.get("JIRA_APPLICATION_FIELD", "customfield_11700"),
        epic_link_field=current_app.config.get("JIRA_EPIC_LINK_FIELD", "customfield_10100"),
    ))


def tableau_service() -> TableauService:
    return _memoized("tableau", lambda: TableauService(
        base_url=current_app.config.get("TABLEAU_BASE_URL", ""),
        api_version=current_app.config.get("TABLEAU_API_VERSION", "3.25"),
        site_content_url=current_app.config.get("TABLEAU_SITE_CONTENT_URL", ""),
        timeout_seconds=current_app.config.get("EXTERNAL_HTTP_TIMEOUT_SECONDS", 20),
    ))
