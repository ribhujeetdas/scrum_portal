from __future__ import annotations

import copy
import hashlib
import re
import time
from typing import Any

from app.core.http_client import ExternalHttpClient, ExternalServiceError


class RuleCopierServiceError(Exception):
    def __init__(self, message: str, *, definitive: bool = False, fallback_kind: str | None = None, outcome: str = "not_sent"):
        super().__init__(message)
        self.definitive = definitive
        self.fallback_kind = fallback_kind
        self.outcome = outcome


class RuleCopierDefinitiveRejection(RuleCopierServiceError):
    def __init__(self, message: str, *, fallback_kind: str):
        super().__init__(message, definitive=True, fallback_kind=fallback_kind, outcome="rejected")


class RuleCopierDestinationSecretError(RuleCopierServiceError):
    def __init__(self, secret_key: str):
        self.secret_key = secret_key
        super().__init__(
            f'Automation secret "{secret_key}" is not available to the destination project scope.',
            definitive=True,
            outcome="rejected",
        )


_SENSITIVE_FIELD_NAMES = {
    "authorization",
    "bearer",
    "token",
    "accesstoken",
    "authtoken",
    "pat",
    "apikey",
    "apitoken",
    "password",
    "passwd",
    "secret",
    "secretvalue",
    "secretkey",
    "credential",
    "credentials",
    "privatekey",
    "clientsecret",
}
_HEADER_NAME_KEYS = {"name", "key", "header", "headername"}
_HEADER_VALUE_KEYS = {"value", "values", "headervalue"}
_SECRET_MARKER_KEYS = {"secret", "issecret", "headersecure", "sensitive", "encrypted"}
_SECRET_REFERENCE_KEYS = {"key", "keyorvalue", "secretkey"}
_VARIABLE_NAME_KEYS = {"variablename", "variablekey"}
_VARIABLE_VALUE_KEYS = {"value", "variablevalue", "smartvalue"}
_CREDENTIAL_PLACEHOLDER = "REPLACE_WITH_DESTINATION_CREDENTIAL"
_SENSITIVE_LITERAL_PATTERN = re.compile(
    r"\b(?:bearer|basic|token|pat|api[_ -]?key|secret|password|credential)\b",
    re.IGNORECASE,
)
_SMART_VALUE_PATTERN = re.compile(r"^\s*\{\{.+\}\}\s*$", re.DOTALL)


def _normalized_field_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _is_sensitive_field_name(value: Any) -> bool:
    normalized = _normalized_field_name(value)
    return (
        normalized in _SENSITIVE_FIELD_NAMES
        or "authorization" in normalized
        or "bearer" in normalized
        or "token" in normalized
        or "secret" in normalized
        or "credential" in normalized
        or normalized.endswith("pat")
        or normalized.endswith("apikey")
        or normalized.endswith("password")
    )


def _contains_sensitive_literal(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_SENSITIVE_LITERAL_PATTERN.search(value))
    if isinstance(value, dict):
        return any(
            (
                _is_sensitive_field_name(key)
                and not (
                    _normalized_field_name(key) in _SECRET_MARKER_KEYS
                    and isinstance(item, bool)
                )
            )
            or _contains_sensitive_literal(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_literal(item) for item in value)
    return False


def _is_smart_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_SMART_VALUE_PATTERN.fullmatch(value))
    if isinstance(value, dict):
        for key, item in value.items():
            if _normalized_field_name(key) in _SECRET_REFERENCE_KEYS:
                return _is_smart_value(item)
    return False


def _secret_names_from(node: dict) -> set[str]:
    for key, value in node.items():
        if _normalized_field_name(key) != "usedsecretskeys":
            continue
        if not isinstance(value, list):
            return set()
        return {
            str(item).strip()
            for item in value
            if isinstance(item, str) and str(item).strip()
        }
    return set()


def _is_managed_secret_reference(value: Any, secret_names: set[str]) -> bool:
    if not isinstance(value, dict):
        return False

    for key, item in value.items():
        normalized = _normalized_field_name(key)
        if normalized in _SECRET_MARKER_KEYS and item is True:
            return True
        if (
            normalized in _SECRET_REFERENCE_KEYS
            and isinstance(item, str)
            and item in secret_names
        ):
            return True
    return False


def _placeholder_for(value: Any) -> Any:
    if isinstance(value, dict):
        placeholder = copy.deepcopy(value)
        replaced = False
        for key, item in list(placeholder.items()):
            normalized = _normalized_field_name(key)
            if normalized in _SECRET_MARKER_KEYS and isinstance(item, bool):
                placeholder[key] = False
            elif normalized in _SECRET_REFERENCE_KEYS or normalized in _VARIABLE_VALUE_KEYS:
                placeholder[key] = _CREDENTIAL_PLACEHOLDER
                replaced = True
        if not replaced:
            placeholder["keyOrValue"] = _CREDENTIAL_PLACEHOLDER
        return placeholder
    if isinstance(value, list):
        return [_CREDENTIAL_PLACEHOLDER]
    return _CREDENTIAL_PLACEHOLDER


def sanitize_sensitive_rule_data(rule_json: dict) -> tuple[dict, dict]:
    """Preserve rule structure while replacing cross-project credential values."""
    if not isinstance(rule_json, dict):
        raise RuleCopierServiceError("rule_json must be an object/dict.")

    redacted_header_names: set[str] = set()
    redacted_field_names: set[str] = set()
    source_secret_names: set[str] = set()
    redacted_count = 0

    def record_header(name: Any) -> None:
        nonlocal redacted_count
        redacted_count += 1
        label = str(name or "Sensitive header").strip()[:100]
        redacted_header_names.add(label or "Sensitive header")

    def record_field(name: Any) -> None:
        nonlocal redacted_count
        redacted_count += 1
        label = str(name or "sensitive field").strip()[:100]
        redacted_field_names.add(label or "sensitive field")

    def entry_header_name(entry: dict) -> str:
        for key, value in entry.items():
            if _normalized_field_name(key) in _HEADER_NAME_KEYS:
                return str(value or "").strip()
        return ""

    def is_header_entry(entry: dict) -> bool:
        keys = {_normalized_field_name(key) for key in entry}
        return bool(keys & _HEADER_NAME_KEYS) and bool(keys & _HEADER_VALUE_KEYS)

    def header_value(entry: dict) -> tuple[str | None, Any]:
        for key, value in entry.items():
            if _normalized_field_name(key) in _HEADER_VALUE_KEYS:
                return key, value
        return None, None

    def sensitive_header_entry(
        entry: Any, secret_names: set[str]
    ) -> tuple[bool, str]:
        if isinstance(entry, str):
            name = entry.split(":", 1)[0].strip()
            return (
                _is_sensitive_field_name(name)
                or (_contains_sensitive_literal(entry) and not _is_smart_value(entry)),
                name,
            )
        if not isinstance(entry, dict):
            return False, ""

        name = entry_header_name(entry)
        _value_key, value = header_value(entry)
        if _is_managed_secret_reference(value, secret_names):
            return True, name
        if _is_smart_value(value):
            return False, name
        if _is_sensitive_field_name(name) or _contains_sensitive_literal(value):
            return True, name
        return False, name

    def replace_header_value(entry: Any) -> Any:
        if isinstance(entry, str):
            name = entry.split(":", 1)[0].strip()
            return f"{name}: {_CREDENTIAL_PLACEHOLDER}"
        if not isinstance(entry, dict):
            return copy.deepcopy(entry)

        sanitized = copy.deepcopy(entry)
        for key, value in list(sanitized.items()):
            if (
                _normalized_field_name(key) in _SECRET_MARKER_KEYS
                and isinstance(value, bool)
            ):
                sanitized[key] = False
        value_key, value = header_value(sanitized)
        if value_key is not None:
            sanitized[value_key] = _placeholder_for(value)
        else:
            sanitized["value"] = _CREDENTIAL_PLACEHOLDER
        return sanitized

    def sanitize_headers(headers: Any, secret_names: set[str]) -> Any:
        if isinstance(headers, list):
            kept = []
            for entry in headers:
                sensitive, name = sensitive_header_entry(entry, secret_names)
                if sensitive:
                    record_header(name)
                    kept.append(replace_header_value(entry))
                else:
                    kept.append(sanitize_node(entry, secret_names=secret_names))
            return kept

        if isinstance(headers, dict):
            if is_header_entry(headers):
                sensitive, name = sensitive_header_entry(headers, secret_names)
                if sensitive:
                    record_header(name)
                    return replace_header_value(headers)
                return sanitize_node(headers, secret_names=secret_names)

            kept = {}
            for name, value in headers.items():
                if _is_smart_value(value):
                    kept[name] = copy.deepcopy(value)
                elif (
                    _is_sensitive_field_name(name)
                    or _is_managed_secret_reference(value, secret_names)
                    or _contains_sensitive_literal(value)
                ):
                    record_header(name)
                    kept[name] = _placeholder_for(value)
                else:
                    kept[name] = sanitize_node(value, secret_names=secret_names)
            return kept

        sensitive, name = sensitive_header_entry(headers, secret_names)
        if sensitive:
            record_header(name)
            return replace_header_value(headers)
        return copy.deepcopy(headers)

    def sanitize_node(
        node: Any,
        *,
        secret_names: set[str] | None = None,
        variable_context: bool = False,
        field_label: str = "",
    ) -> Any:
        inherited_secret_names = set(secret_names or ())
        if isinstance(node, dict):
            local_secret_names = inherited_secret_names | _secret_names_from(node)
            source_secret_names.update(_secret_names_from(node))

            if _is_managed_secret_reference(node, local_secret_names):
                record_field(field_label or "Jira secret reference")
                return _placeholder_for(node)

            node_type = str(node.get("type") or "").casefold()
            local_variable_context = variable_context or "variable" in node_type
            variable_name = ""
            for key, value in node.items():
                normalized = _normalized_field_name(key)
                if normalized in _VARIABLE_NAME_KEYS or (
                    local_variable_context and normalized in {"name", "key"}
                ):
                    variable_name = str(value or "").strip()
                    break
            redact_variable = bool(
                variable_name and _is_sensitive_field_name(variable_name)
            )

            sanitized = {}
            for key, value in node.items():
                normalized = _normalized_field_name(key)
                if normalized == "usedsecretskeys":
                    sanitized[key] = []
                    continue
                if normalized.endswith("headers"):
                    sanitized[key] = sanitize_headers(value, local_secret_names)
                    continue
                if redact_variable and normalized in _VARIABLE_VALUE_KEYS:
                    sanitized[key] = _placeholder_for(value)
                    record_field(variable_name)
                    continue
                if normalized in _SECRET_MARKER_KEYS and isinstance(value, bool):
                    sanitized[key] = value
                    continue
                if _is_sensitive_field_name(key):
                    sanitized[key] = _placeholder_for(value)
                    record_field(key)
                    continue
                sanitized[key] = sanitize_node(
                    value,
                    secret_names=local_secret_names,
                    variable_context=local_variable_context,
                    field_label=key,
                )
            return sanitized
        if isinstance(node, list):
            return [
                sanitize_node(
                    item,
                    secret_names=inherited_secret_names,
                    variable_context=variable_context,
                    field_label=field_label,
                )
                for item in node
            ]
        return copy.deepcopy(node)

    sanitized_rule = sanitize_node(rule_json)
    report = {
        "redacted_count": redacted_count,
        "redacted_header_names": sorted(redacted_header_names, key=str.casefold),
        "redacted_field_names": sorted(redacted_field_names, key=str.casefold),
        "source_secret_names": sorted(source_secret_names, key=str.casefold),
    }
    return sanitized_rule, report


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
        if not isinstance(data, dict):
            return []

        rules = data.get("rules") or data.get("values") or []
        if isinstance(rules, list):
            return rules
        if isinstance(rules, dict):
            nested_rules = rules.get("rules") or rules.get("values") or []
            return nested_rules if isinstance(nested_rules, list) else []
        return []

    def get_rule_detail(self, project_identifier: str | int, rule_id: int, pat: str) -> dict:
        """
        Best-effort:
          1) Prefer a complete definition returned by the Data Center rule list.
          2) Try GET /rule/{rule_id} when the list only contains summaries.
          3) Fall back to the listed rule when the detail endpoint is unsupported.

        (Internal endpoints vary across DC instances) [1](https://developer.atlassian.com/server/jira/platform/rest/v10000/)
        """
        listed_rule = None
        list_error = None
        try:
            listed_rule = self.find_rule(
                self.list_rules_for_project(project_identifier, pat), rule_id
            )
        except RuleCopierServiceError as exc:
            list_error = exc

        if listed_rule and (
            isinstance(listed_rule.get("components"), list)
            or isinstance(listed_rule.get("trigger"), dict)
        ):
            return listed_rule

        try:
            detail = self._client.get_json(
                f"/rest/cb-automation/latest/project/{project_identifier}/rule/{rule_id}",
                headers=self._headers(pat),
            )
            if isinstance(detail, dict):
                return detail
        except ExternalServiceError:
            pass

        if listed_rule:
            return listed_rule
        if list_error:
            raise list_error
        raise RuleCopierServiceError(
            "Rule not found in automation rule list for this project."
        )

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
    def transform_rule_for_create(self, rule_json: dict, target_project_id: int, author_account_id: str, actor_account_id: str, idempotency_key: str | None = None) -> dict:
        """
        Takes fetched rule JSON and transforms into a payload suitable for create.

        Based on common create payload patterns (keys like name, isNewRule, state, trigger, components, projects, etc).
        Payload structures vary per DC instance/version; this is best-effort. [1](https://developer.atlassian.com/server/jira/platform/rest/v10000/)
        """
        if not isinstance(rule_json, dict):
            raise RuleCopierServiceError("rule_json must be an object/dict.")

        payload, _sanitization = sanitize_sensitive_rule_data(rule_json)

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
        component_index = 0

        def _rewrite_component_ids(obj):
            nonlocal component_index
            if isinstance(obj, dict):
                if "id" in obj and isinstance(obj["id"], str) and obj["id"].startswith("__NEW__"):
                    component_index += 1
                    if idempotency_key:
                        digest = hashlib.sha256(
                            f"{idempotency_key}:{component_index}".encode("utf-8")
                        ).hexdigest()
                        suffix = int(digest[:13], 16)
                    else:
                        suffix = int(time.time() * 1000) + component_index
                    obj["id"] = f"__NEW__{suffix}"
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
        finally:
            resp.close()

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
        snippet = self._snippet(exc)
        if exc.status_code == 400 and "PROJECT_IDENTIFIER_UNSUPPORTED" in snippet:
            raise RuleCopierDefinitiveRejection(
                "Jira definitively rejected the numeric project identifier.",
                fallback_kind="project_identifier",
            ) from exc
        if exc.status_code == 400 and "ACTOR_ACCOUNT_ID_INVALID" in snippet:
            raise RuleCopierDefinitiveRejection(
                "Jira definitively rejected the configured automation actor.",
                fallback_kind="actor",
            ) from exc
        secret_match = re.search(
            r"A secret with key ([A-Za-z0-9_.-]{1,100}) does not exist or is not allowed",
            snippet,
            re.IGNORECASE,
        )
        if exc.status_code == 400 and secret_match:
            raise RuleCopierDestinationSecretError(secret_match.group(1)) from exc
        if exc.status_code is not None:
            raise RuleCopierServiceError(
                f"Create rule API error: {exc.status_code}",
                definitive=exc.status_code < 500,
                outcome=exc.outcome,
            ) from exc
        raise RuleCopierServiceError(
            "Network error calling create rule API.", outcome="unknown") from exc
