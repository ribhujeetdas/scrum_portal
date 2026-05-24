# app/services/jira_issue_links_service.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.core.http_client import ExternalHttpClient, ExternalServiceError


class JiraIssueLinksServiceError(Exception):
    pass


@dataclass(frozen=True)
class JiraRelatedTicketResult:
    ok: bool
    feature_key: str
    mapped_key: str
    application_id: str
    matches: List[Dict[str, Any]]
    message: str


class JiraIssueLinksService:
    """
    Fetch issue links for a feature key and validate if there exists an inward related ticket
    that belongs to mapped_key (e.g. PKLGX/PBGXJ) and has label for application id.
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 20,
        http_client: ExternalHttpClient | None = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        if not self.base_url:
            raise ValueError("JIRA_BASE_URL is missing.")
        self.timeout = timeout_seconds
        self._client = http_client or ExternalHttpClient(
            "jira", self.base_url, timeout_seconds=timeout_seconds
        )

    def _headers(self, pat: str) -> dict:
        return {
            "Authorization": f"Bearer {pat}",
            "Accept": "application/json",
        }

    def fetch_issue_links(self, issue_key: str, pat: str) -> List[dict]:
        params = {"fields": "issuelinks"}
        try:
            data = self._client.get_json(
                f"/rest/api/2/issue/{issue_key}",
                headers=self._headers(pat),
                params=params,
            )
        except ExternalServiceError as exc:
            if exc.status_code == 401:
                raise JiraIssueLinksServiceError(
                    "Unauthorized (401). Check Jira PAT.") from exc
            if exc.status_code == 403:
                raise JiraIssueLinksServiceError(
                    "Forbidden (403). PAT lacks permission.") from exc
            if exc.status_code == 404:
                raise JiraIssueLinksServiceError(
                    f"Issue not found (404): {issue_key}") from exc
            if exc.status_code is not None:
                raise JiraIssueLinksServiceError(
                    f"Jira error {exc.status_code}: {(exc.response_snippet or '')[:200]}") from exc
            raise JiraIssueLinksServiceError(
                f"Network error fetching issue links: {exc}") from exc
        fields = data.get("fields") or {}
        return fields.get("issuelinks") or []

    def fetch_issue_details_by_self(self, issue_self_url: str, pat: str) -> dict:
        params = {"fields": "labels,key,summary,status"}
        try:
            return self._client.get_json(
                issue_self_url,
                headers=self._headers(pat),
                params=params,
            )
        except ExternalServiceError as exc:
            if exc.status_code == 401:
                raise JiraIssueLinksServiceError(
                    "Unauthorized (401). Check Jira PAT.") from exc
            if exc.status_code == 403:
                raise JiraIssueLinksServiceError(
                    "Forbidden (403). PAT lacks permission.") from exc
            if exc.status_code == 404:
                raise JiraIssueLinksServiceError("Inward issue not found (404).") from exc
            if exc.status_code is not None:
                raise JiraIssueLinksServiceError(
                    f"Jira error {exc.status_code}: {(exc.response_snippet or '')[:200]}") from exc
            raise JiraIssueLinksServiceError(
                f"Network error fetching inward issue details: {exc}") from exc

    @staticmethod
    def _is_relates_type(t: dict) -> bool:
        name = (t.get("name") or "").strip().lower()
        inward = (t.get("inward") or "").strip().lower()
        outward = (t.get("outward") or "").strip().lower()
        if name != "relates":
            return False
        # also validate inward/outward strings contain relates
        return ("relate" in inward) and ("relate" in outward)

    @staticmethod
    def _key_matches_mapped(inward_key: str, mapped_key: str) -> bool:
        # "contains" requirement, but safest is prefix match
        # Accept both "PKLGX-123" and any containing mapped_key token
        ik = (inward_key or "").strip().upper()
        mk = (mapped_key or "").strip().upper()
        if not ik or not mk:
            return False
        return ik.startswith(mk + "-") or (mk in ik)

    @staticmethod
    def _labels_match_app(labels: List[str], app_id: str) -> bool:
        if not labels:
            return False
        aid = (app_id or "").strip().lower()
        if not aid:
            return False
        for lab in labels:
            l = (lab or "").strip().lower()
            if l == aid:
                return True
            if l == f"appid:{aid}":
                return True
        return False

    def validate_related_ticket(
        self,
        feature_key: str,
        mapped_key: str,
        application_id: str,
        pat: str,
    ) -> JiraRelatedTicketResult:

        issuelinks = self.fetch_issue_links(feature_key, pat)

        matches: List[Dict[str, Any]] = []

        for link in issuelinks:
            t = link.get("type") or {}
            if not self._is_relates_type(t):
                continue

            inward = link.get("inwardIssue") or {}
            inward_key = inward.get("key") or ""
            inward_self = inward.get("self") or ""

            if not inward_key or not inward_self:
                continue

            if not self._key_matches_mapped(inward_key, mapped_key):
                continue

            details = self.fetch_issue_details_by_self(inward_self, pat)
            fields = details.get("fields") or {}
            labels = fields.get("labels") or []
            status = (fields.get("status") or {}).get("name") or ""
            summary = fields.get("summary") or ""
            issue_key = details.get("key") or inward_key

            label_ok = self._labels_match_app(labels, application_id)

            matches.append(
                {
                    "inward_issue_key": issue_key,
                    "inward_issue_self": inward_self,
                    "link_type": {
                        "name": t.get("name"),
                        "inward": t.get("inward"),
                        "outward": t.get("outward"),
                    },
                    "inward_summary": summary,
                    "inward_status": status,
                    "labels": labels,
                    "label_match": label_ok,
                }
            )

        if not matches:
            return JiraRelatedTicketResult(
                ok=True,
                feature_key=feature_key,
                mapped_key=mapped_key,
                application_id=application_id,
                matches=[],
                message="No matching inward related ticket found for the mapped key.",
            )

        return JiraRelatedTicketResult(
            ok=True,
            feature_key=feature_key,
            mapped_key=mapped_key,
            application_id=application_id,
            matches=matches,
            message="Related ticket(s) found. Check label_match for application id validation.",
        )
