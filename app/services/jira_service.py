from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class JiraServiceError(Exception):
    pass


class JiraService:
    """
    Jira Data Center PAT validation service.
    Uses Authorization: Bearer <PAT> to call /rest/api/2/myself
    """

    def __init__(self, base_url: str, timeout_seconds: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds
        if not self.base_url:
            raise ValueError("JIRA_BASE_URL is missing.")

        self._session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retries))
        self._session.mount("http://", HTTPAdapter(max_retries=retries))

    def fetch_myself(self, pat: str) -> dict:
        url = f"{self.base_url}/rest/api/2/myself"
        headers = {
            "Authorization": f"Bearer {pat}",
            "Accept": "application/json",
        }

        try:
            resp = self._session.get(
                url, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise JiraServiceError(
                f"Network error calling Jira: {exc}") from exc

        if resp.status_code == 401:
            raise JiraServiceError("Invalid Jira PAT (401 Unauthorized).")
        if resp.status_code == 403:
            raise JiraServiceError(
                "Jira PAT lacks permission (403 Forbidden).")
        if resp.status_code >= 400:
            raise JiraServiceError(
                f"Jira error {resp.status_code}: {resp.text[:200]}")

        try:
            return resp.json()
        except ValueError as exc:
            raise JiraServiceError("Invalid JSON from Jira.") from exc
