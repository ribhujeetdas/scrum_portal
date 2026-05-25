from __future__ import annotations

from flask import current_app

from app.services.crypto_service import CryptoService
from app.services.jira_issue_links_service import JiraIssueLinksService
from app.services.jira_projects_service import JiraProjectsService
from app.services.jira_service import JiraService
from app.services.rule_copier_service import RuleCopierService
from app.services.sprint_viewer_service import SprintViewerService
from app.services.tableau_service import TableauService


def crypto_service() -> CryptoService:
    return CryptoService(current_app.config["FERNET_KEY"])


def jira_service() -> JiraService:
    return JiraService(
        current_app.config["JIRA_BASE_URL"],
        timeout_seconds=current_app.config.get("EXTERNAL_HTTP_TIMEOUT_SECONDS", 20),
    )


def jira_projects_service() -> JiraProjectsService:
    return JiraProjectsService(
        current_app.config["JIRA_BASE_URL"],
        timeout_seconds=current_app.config.get("EXTERNAL_HTTP_TIMEOUT_SECONDS", 20),
    )


def jira_issue_links_service() -> JiraIssueLinksService:
    return JiraIssueLinksService(
        current_app.config.get("JIRA_BASE_URL", ""),
        timeout_seconds=current_app.config.get("EXTERNAL_HTTP_TIMEOUT_SECONDS", 20),
    )


def rule_copier_service() -> RuleCopierService:
    return RuleCopierService(
        current_app.config["JIRA_BASE_URL"],
        timeout_seconds=current_app.config.get("EXTERNAL_HTTP_TIMEOUT_SECONDS", 30),
    )


def sprint_viewer_service() -> SprintViewerService:
    return SprintViewerService(
        current_app.config["JIRA_BASE_URL"],
        timeout_seconds=current_app.config.get(
            "SPRINT_METRICS_HTTP_TIMEOUT_SECONDS",
            current_app.config.get("EXTERNAL_HTTP_TIMEOUT_SECONDS", 30),
        ),
        metrics_max_workers=current_app.config.get("SPRINT_METRICS_MAX_WORKERS", 5),
    )


def tableau_service() -> TableauService:
    return TableauService(
        base_url=current_app.config.get("TABLEAU_BASE_URL", ""),
        api_version=current_app.config.get("TABLEAU_API_VERSION", "3.25"),
        site_content_url=current_app.config.get("TABLEAU_SITE_CONTENT_URL", ""),
        timeout_seconds=current_app.config.get("EXTERNAL_HTTP_TIMEOUT_SECONDS", 20),
    )
