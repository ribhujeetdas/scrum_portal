# app/services/jira_issue_links_service.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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

    def __init__(self, base_url: str, timeout_seconds: int = 20):
        self.base_url = (base_url or "").rstrip("/")
        if not self.base_url:
            raise ValueError("JIRA_BASE_URL is missing.")
        self.timeout = timeout_seconds
        self._session = requests.Session()

        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retries))
        self._session.mount("http://", HTTPAdapter(max_retries=retries))

    def _headers(self, pat: str) -> dict:
        return {
            "Authorization": f"Bearer {pat}",
            "Accept": "application/json",
        }

    def fetch_issue_links(self, issue_key: str, pat: str) -> List[dict]:
        url = f"{self.base_url}/rest/api/2/issue/{issue_key}"
        params = {"fields": "issuelinks"}
        try:
            resp = self._session.get(url, headers=self._headers(
                pat), params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise JiraIssueLinksServiceError(
                f"Network error fetching issue links: {exc}") from exc

        if resp.status_code == 401:
            raise JiraIssueLinksServiceError(
                "Unauthorized (401). Check Jira PAT.")
        if resp.status_code == 403:
            raise JiraIssueLinksServiceError(
                "Forbidden (403). PAT lacks permission.")
        if resp.status_code == 404:
            raise JiraIssueLinksServiceError(
                f"Issue not found (404): {issue_key}")
        if resp.status_code >= 400:
            raise JiraIssueLinksServiceError(
                f"Jira error {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        fields = data.get("fields") or {}
        return fields.get("issuelinks") or []

    def fetch_issue_details_by_self(self, issue_self_url: str, pat: str) -> dict:
        params = {"fields": "labels,key,summary,status"}
        try:
            resp = self._session.get(issue_self_url, headers=self._headers(
                pat), params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise JiraIssueLinksServiceError(
                f"Network error fetching inward issue details: {exc}") from exc

        if resp.status_code == 401:
            raise JiraIssueLinksServiceError(
                "Unauthorized (401). Check Jira PAT.")
        if resp.status_code == 403:
            raise JiraIssueLinksServiceError(
                "Forbidden (403). PAT lacks permission.")
        if resp.status_code == 404:
            raise JiraIssueLinksServiceError("Inward issue not found (404).")
        if resp.status_code >= 400:
            raise JiraIssueLinksServiceError(
                f"Jira error {resp.status_code}: {resp.text[:200]}")

        return resp.json()

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
