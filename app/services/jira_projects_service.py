# app/services/jira_projects_service.py
from __future__ import annotations

from typing import Optional, List, Dict, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class JiraProjectsServiceError(Exception):
    pass


class JiraProjectsService:
    """
    Jira Data Center:
    - Check permissions via: GET /rest/api/2/mypermissions?projectKey=KEY
    - List boards via: GET /rest/agile/1.0/board?projectKeyOrId=KEY
    - List projects associated with a board via:
        GET /rest/agile/1.0/board/{boardId}/project  (and /project/full)
      Used to detect Product Area project key from board association. [1](https://docs.atlassian.com/software/jira/docs/api/REST/9.13.0/)[3](https://developer.atlassian.com/server/jira/platform/jira-rest-api-examples/)
    """

    def __init__(self, base_url: str, timeout_seconds: int = 20):
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

    def _headers(self, pat: str) -> dict:
        return {
            "Authorization": f"Bearer {pat}",
            "Accept": "application/json",
        }

    def has_administer_projects(self, project_key: str, pat: str) -> bool:
        """
        Calls:
          GET /rest/api/2/mypermissions?projectKey={projectKey}
        Parses:
          permissions.ADMINISTER_PROJECTS.havePermission == True
        """
        url = f"{self.base_url}/rest/api/2/mypermissions"
        params = {"projectKey": project_key}
        try:
            resp = self._session.get(url, headers=self._headers(
                pat), params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise JiraProjectsServiceError(
                f"Network error calling mypermissions: {exc}") from exc

        if resp.status_code == 401:
            raise JiraProjectsServiceError(
                "Unauthorized (401) while checking permissions. Check PAT.")
        if resp.status_code == 403:
            raise JiraProjectsServiceError(
                "Forbidden (403) while checking permissions.")
        if resp.status_code == 404:
            raise JiraProjectsServiceError(
                "Project not found (404). Check project key.")
        if resp.status_code >= 400:
            raise JiraProjectsServiceError(
                f"Error checking permissions: {resp.status_code} {resp.text[:200]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise JiraProjectsServiceError(
                "Invalid JSON returned by mypermissions.") from exc

        perms = data.get("permissions") or {}
        admin = perms.get("ADMINISTER_PROJECTS") or {}
        return bool(admin.get("havePermission"))

    def list_boards_for_project(self, project_key: str, pat: str) -> list[dict]:
        """
        Calls:
          GET /rest/agile/1.0/board?projectKeyOrId={projectKey}
        Handles pagination using startAt/maxResults/isLast if present.
        Returns list of {board_id, board_name, board_type, board_url}
        """
        all_boards: list[dict] = []
        start_at = 0
        max_results = 50

        while True:
            url = f"{self.base_url}/rest/agile/1.0/board"
            params = {
                "projectKeyOrId": project_key,
                "startAt": start_at,
                "maxResults": max_results,
            }
            try:
                resp = self._session.get(url, headers=self._headers(
                    pat), params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                raise JiraProjectsServiceError(
                    f"Network error listing boards: {exc}") from exc

            if resp.status_code == 401:
                raise JiraProjectsServiceError(
                    "Unauthorized (401) while listing boards. Check PAT.")
            if resp.status_code == 403:
                raise JiraProjectsServiceError(
                    "Forbidden (403) while listing boards.")
            if resp.status_code >= 400:
                raise JiraProjectsServiceError(
                    f"Error listing boards: {resp.status_code} {resp.text[:200]}")

            try:
                data = resp.json()
            except ValueError as exc:
                raise JiraProjectsServiceError(
                    "Invalid JSON returned by board API.") from exc

            values = data.get("values") or []
            for b in values:
                all_boards.append(
                    {
                        "board_id": int(b.get("id")),
                        "board_name": (b.get("name") or "").strip(),
                        "board_type": (b.get("type") or "").strip(),
                        "board_url": (b.get("self") or "").strip(),
                    }
                )

            is_last = data.get("isLast")
            total = data.get("total")

            if is_last is True:
                break

            if isinstance(total, int):
                start_at += max_results
                if start_at >= total:
                    break
            else:
                break

        return all_boards

    # ---------------------------------------------------------------------
    # NEW: Board -> Projects (to find Product Area project key)
    # ---------------------------------------------------------------------

    def list_projects_for_board(self, board_id: int, pat: str) -> List[Dict[str, Any]]:
        """
        Calls:
          GET /rest/agile/1.0/board/{boardId}/project
        Returns: list of project objects in "values".
        This endpoint returns projects statically associated with the board. [1](https://docs.atlassian.com/software/jira/docs/api/REST/9.13.0/)[3](https://developer.atlassian.com/server/jira/platform/jira-rest-api-examples/)
        """
        all_projects: List[Dict[str, Any]] = []
        start_at = 0
        max_results = 50

        while True:
            url = f"{self.base_url}/rest/agile/1.0/board/{int(board_id)}/project"
            params = {"startAt": start_at, "maxResults": max_results}
            try:
                resp = self._session.get(url, headers=self._headers(
                    pat), params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                raise JiraProjectsServiceError(
                    f"Network error listing board projects: {exc}") from exc

            if resp.status_code == 401:
                raise JiraProjectsServiceError(
                    "Unauthorized (401) while listing board projects. Check PAT.")
            if resp.status_code == 403:
                raise JiraProjectsServiceError(
                    "Forbidden (403) while listing board projects.")
            if resp.status_code >= 400:
                raise JiraProjectsServiceError(
                    f"Error listing board projects: {resp.status_code} {resp.text[:200]}")

            try:
                data = resp.json()
            except ValueError as exc:
                raise JiraProjectsServiceError(
                    "Invalid JSON returned by board projects API.") from exc

            values = data.get("values") or []
            all_projects.extend(values)

            is_last = data.get("isLast")
            total = data.get("total")

            if is_last is True:
                break

            if isinstance(total, int):
                start_at += max_results
                if start_at >= total:
                    break
            else:
                break

        return all_projects

    @staticmethod
    def extract_product_area_project_key(projects: List[Dict[str, Any]]) -> Optional[str]:
        """
        From list of board-associated projects, return the project key where:
           projectCategory.name == "Product Area"
        Returns None if not found.
        """
        for p in projects or []:
            cat = p.get("projectCategory") or {}
            cat_name = (cat.get("name") or "").strip()
            if cat_name.lower() == "product area":
                key = (p.get("key") or "").strip().upper()
                return key or None
        return None

    def get_product_area_project_key_for_board(self, board_id: int, pat: str) -> Optional[str]:
        """
        Convenience:
          list_projects_for_board(board_id) -> extract_product_area_project_key(...)
        """
        projects = self.list_projects_for_board(board_id, pat)
        return self.extract_product_area_project_key(projects)
