from __future__ import annotations

from app.core.http_client import ExternalHttpClient, ExternalServiceError


class JiraServiceError(Exception):
    pass


class JiraService:
    """
    Jira Data Center PAT validation service.
    Uses Authorization: Bearer <PAT> to call /rest/api/2/myself
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 10,
        http_client: ExternalHttpClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds
        if not self.base_url:
            raise ValueError("JIRA_BASE_URL is missing.")

        self._client = http_client or ExternalHttpClient(
            "jira", self.base_url, timeout_seconds=timeout_seconds
        )

    def fetch_myself(self, pat: str) -> dict:
        headers = {
            "Authorization": f"Bearer {pat}",
            "Accept": "application/json",
        }

        try:
            return self._client.get_json("/rest/api/2/myself", headers=headers)
        except ExternalServiceError as exc:
            if exc.message == "Invalid JSON response":
                raise JiraServiceError("Invalid JSON from Jira.") from exc
            if exc.status_code == 401:
                raise JiraServiceError("Invalid Jira PAT (401 Unauthorized).") from exc
            if exc.status_code == 403:
                raise JiraServiceError("Jira PAT lacks permission (403 Forbidden).") from exc
            if exc.status_code is not None:
                raise JiraServiceError(
                    f"Jira error {exc.status_code}: {(exc.response_snippet or '')[:200]}"
                ) from exc
            raise JiraServiceError(f"Network error calling Jira: {exc}") from exc
