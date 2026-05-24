from __future__ import annotations

import copy
import time

from app.core.http_client import ExternalHttpClient, ExternalServiceError


class RuleCopierServiceError(Exception):
    pass


class RuleCopierService:
    """
    Implements:
    1) Resolve projectId+projectKey from board issues endpoint:
       GET /rest/agile/1.0/board/{board_id}/issue?maxResults=1  

    2) Fetch/list automation rules for project:
       GET /rest/cb-automation/latest/project/{project_identifier}/rule
       GET /rest/cb-automation/latest/project/{project_identifier}/rule/{rule_id}
       (Internal endpoint patterns vary across DC instances)

    3) Create rule:
       POST /rest/cb-automation/latest/project/{project_identifier}/rule
       (Internal endpoint patterns vary across DC instances) 
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 30,
        http_client: ExternalHttpClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds
        if not self.base_url:
            raise ValueError("JIRA_BASE_URL is missing.")

        self._client = http_client or ExternalHttpClient(
            "jira", self.base_url, timeout_seconds=timeout_seconds
        )

    def _headers(self, pat: str) -> dict:
        return {
            "Authorization": f"Bearer {pat}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # ---------------------------
    # Project resolution (Board -> Project)
    # ---------------------------
    def resolve_project_from_board_issue(self, board_id: int, pat: str) -> dict:
        """
        Calls:
          GET /rest/agile/1.0/board/{board_id}/issue?maxResults=1  

        Extracts:
          issues[0].fields.project.id
          issues[0].fields.project.key
        """
        params = {"maxResults": 1}

        try:
            data = self._client.get_json(
                f"/rest/agile/1.0/board/{board_id}/issue",
                headers=self._headers(pat),
                params=params,
            )
        except ExternalServiceError as exc:
            self._raise_board_issue_error(exc)

        issues = data.get("issues") or []
        if not issues:
            raise RuleCopierServiceError(
                "No issues returned for selected board. Cannot determine project id/key from board."
            )

        fields = issues[0].get("fields") or {}
        project = fields.get("project") or {}

        project_id = project.get("id")
        project_key = project.get("key")

        if project_id is None or project_key is None:
            raise RuleCopierServiceError(
                "Could not extract project.id/project.key from board issue response.")

        try:
            project_id_int = int(project_id)
        except Exception:
            raise RuleCopierServiceError(
                f"Project id is not numeric: {project_id}")

        return {"project_id": project_id_int, "project_key": str(project_key).strip()}

    # ---------------------------
    # Automation rules API helpers
    # ---------------------------
    def list_rules_for_project(self, project_identifier: str | int, pat: str) -> list[dict]:
        """
        Calls:
          GET /rest/cb-automation/latest/project/{project_identifier}/rule
        """
        try:
            data = self._client.get_json(
                f"/rest/cb-automation/latest/project/{project_identifier}/rule",
                headers=self._headers(pat),
            )
        except ExternalServiceError as exc:
            self._raise_automation_api_error(exc, "list")

        if isinstance(data, list):
            return data
        return data.get("rules") or data.get("values") or []

    def get_rule_detail(self, project_identifier: str | int, rule_id: int, pat: str) -> dict:
        """
        Best-effort:
          1) Try GET /rule/{rule_id}
          2) Fallback to listing rules and picking matching id

        (Internal endpoints vary across DC instances) [1](https://developer.atlassian.com/server/jira/platform/rest/v10000/)
        """
        # Attempt detail endpoint
        try:
            return self._client.get_json(
                f"/rest/cb-automation/latest/project/{project_identifier}/rule/{rule_id}",
                headers=self._headers(pat),
            )
        except ExternalServiceError:
            # ignore and fallback
            pass

        # Fallback: list and find
        rules = self.list_rules_for_project(project_identifier, pat)
        found = self.find_rule(rules, rule_id)
        if not found:
            raise RuleCopierServiceError(
                "Rule not found in automation rule list for this project.")
        return found

    def find_rule(self, rules: list[dict], rule_id: int) -> dict | None:
        for r in rules:
            try:
                if int(r.get("id")) == int(rule_id):
                    return r
            except Exception:
                continue
        return None

    # ---------------------------
    # Transform + Create rule
    # ---------------------------
    def transform_rule_for_create(self, rule_json: dict, target_project_id: int, author_account_id: str, actor_account_id: str) -> dict:
        """
        Takes fetched rule JSON and transforms into a payload suitable for create.

        Based on common create payload patterns (keys like name, isNewRule, state, trigger, components, projects, etc).
        Payload structures vary per DC instance/version; this is best-effort. [1](https://developer.atlassian.com/server/jira/platform/rest/v10000/)
        """
        if not isinstance(rule_json, dict):
            raise RuleCopierServiceError("rule_json must be an object/dict.")

        payload = copy.deepcopy(rule_json)

        # Remove server-managed fields that often break create
        for k in (
            "id",
            "self",
            "uuid",
            "created",
            "updated",
            "author",
            "actor",
            "links",
            "statistics",
        ):
            payload.pop(k, None)

        # Ensure name exists
        name = (payload.get("name") or "").strip()
        if name:
            if not name.lower().startswith("copy of"):
                payload["name"] = f"Copy of {name}"
        else:
            payload["name"] = "Copy of Rule"

        # Common flags
        payload["isNewRule"] = True
        payload["state"] = "DISABLED"
        # payload.setdefault("state", "DISABLED")

        payload["authorAccountId"] = str(author_account_id).strip()
        payload["actorAccountId"] = str(actor_account_id).strip()

        # Ensure projects scope
        # Common format: "projects": [{"projectId": "103407", "projectTypeKey": "software"}]
        # We set/overwrite projectId to destination project id.
        projects = payload.get("projects")
        if not isinstance(projects, list) or not projects:
            payload["projects"] = [{"projectId": str(target_project_id)}]
        else:
            # set first entry projectId
            if isinstance(projects[0], dict):
                projects[0]["projectId"] = str(target_project_id)
            else:
                payload["projects"] = [{"projectId": str(target_project_id)}]

        # Some instances require unique component IDs; best-effort to replace "__NEW__" ids
        def _rewrite_component_ids(obj):
            if isinstance(obj, dict):
                if "id" in obj and isinstance(obj["id"], str) and obj["id"].startswith("__NEW__"):
                    obj["id"] = f"__NEW__{int(time.time() * 1000)}"
                for v in obj.values():
                    _rewrite_component_ids(v)
            elif isinstance(obj, list):
                for item in obj:
                    _rewrite_component_ids(item)

        _rewrite_component_ids(payload)

        return payload

    def create_rule(self, project_identifier: str | int, payload: dict, pat: str) -> dict:
        """
        Calls:
          POST /rest/cb-automation/latest/project/{project_identifier}/rule  (https://developer.atlassian.com/server/jira/platform/rest/v10000/)
        """
        try:
            resp = self._client.post(
                f"/rest/cb-automation/latest/project/{project_identifier}/rule",
                headers=self._headers(pat),
                json=payload,
            )
        except ExternalServiceError as exc:
            self._raise_create_rule_error(exc)

        try:
            return resp.json()
        except ValueError:
            return {"status": "success", "http_status": resp.status_code}

    @staticmethod
    def _snippet(exc: ExternalServiceError) -> str:
        return (exc.response_snippet or "")[:200]

    def _raise_board_issue_error(self, exc: ExternalServiceError) -> None:
        if exc.status_code == 401:
            raise RuleCopierServiceError(
                "Unauthorized (401) while calling board issue API. Check PAT.") from exc
        if exc.status_code == 403:
            raise RuleCopierServiceError(
                "Forbidden (403) while calling board issue API.") from exc
        if exc.message == "Invalid JSON response":
            raise RuleCopierServiceError(
                "Invalid JSON returned by board issue API.") from exc
        if exc.status_code is not None:
            raise RuleCopierServiceError(
                f"Board issue API error: {exc.status_code} {self._snippet(exc)}") from exc
        raise RuleCopierServiceError(
            f"Network error calling board issue API: {exc}") from exc

    def _raise_automation_api_error(self, exc: ExternalServiceError, operation: str) -> None:
        if exc.status_code == 401:
            raise RuleCopierServiceError(
                "Unauthorized (401) while calling automation API. Check PAT.") from exc
        if exc.status_code == 403:
            raise RuleCopierServiceError(
                "Forbidden (403) while calling automation API.") from exc
        if exc.message == "Invalid JSON response":
            raise RuleCopierServiceError(
                "Invalid JSON returned by automation API.") from exc
        if exc.status_code is not None:
            raise RuleCopierServiceError(
                f"Automation API error: {exc.status_code} {self._snippet(exc)}") from exc
        raise RuleCopierServiceError(
            f"Network error calling automation rule {operation}: {exc}") from exc

    def _raise_create_rule_error(self, exc: ExternalServiceError) -> None:
        if exc.status_code == 401:
            raise RuleCopierServiceError(
                "Unauthorized (401) while creating rule. Check PAT.") from exc
        if exc.status_code == 403:
            raise RuleCopierServiceError("Forbidden (403) while creating rule.") from exc
        if exc.status_code is not None:
            raise RuleCopierServiceError(
                f"Create rule API error: {exc.status_code} {self._snippet(exc)}") from exc
        raise RuleCopierServiceError(
            f"Network error calling create rule API: {exc}") from exc
