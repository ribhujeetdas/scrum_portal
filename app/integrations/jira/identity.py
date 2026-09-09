from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


def _clean(value: Any) -> str:
    return str(value or "").strip()


@dataclass
class JiraIdentityResolver:
    """Resolve Jira's mutable user aliases to one principal during an import."""

    _aliases: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def _principal(identity: dict[str, Any]) -> str:
        account_id = _clean(identity.get("accountId"))
        key = _clean(identity.get("key"))
        name = _clean(identity.get("name"))
        if account_id:
            return f"account:{account_id}"
        if key:
            return f"key:{key}"
        if name:
            return f"name:{name}"
        return "unassigned"

    def observe(self, identity: dict[str, Any] | None) -> str:
        identity = identity or {}
        principal = self._principal(identity)
        if principal == "unassigned":
            return principal
        for field_name in ("accountId", "key", "name"):
            value = _clean(identity.get(field_name))
            if value:
                self._aliases[value] = principal
        return principal

    def observe_changelog(self, external_id: Any, label: Any) -> str:
        external = _clean(external_id)
        display = _clean(label)
        if not external and not display:
            return "unassigned"
        principal = self._aliases.get(external)
        if principal is None:
            principal = f"key:{external}" if external else f"name:{display}"
        if external:
            self._aliases[external] = principal
        # A label is useful only as import-local evidence; it is never persisted
        # as an authoritative stable identifier.
        if display:
            self._aliases.setdefault(display, principal)
        return principal

    def seed(self, principal: str, *aliases: Any) -> None:
        """Seed a previously persisted principal without treating display labels as identity."""
        if not principal or principal == "unassigned":
            return
        external = principal.partition(":")[2]
        if external:
            self._aliases[external] = principal
        for alias in aliases:
            value = _clean(alias)
            if value:
                self._aliases[value] = principal

    def resolve(self, identity: dict[str, Any] | None) -> str:
        identity = identity or {}
        for field_name in ("accountId", "key", "name"):
            value = _clean(identity.get(field_name))
            if value and value in self._aliases:
                return self._aliases[value]
        return self.observe(identity)


def build_identity_resolver(issues: Iterable[dict[str, Any]]) -> JiraIdentityResolver:
    resolver = JiraIdentityResolver()
    materialized = list(issues)
    for issue in materialized:
        fields = issue.get("fields") or {}
        resolver.observe(fields.get("assignee") or {})
        for comment in ((fields.get("comment") or {}).get("comments") or []):
            resolver.observe(comment.get("author") or {})
    for issue in materialized:
        for history in ((issue.get("changelog") or {}).get("histories") or []):
            for item in history.get("items") or []:
                field_name = str(item.get("field") or item.get("fieldId") or "").lower()
                if field_name != "assignee":
                    continue
                resolver.observe_changelog(item.get("from"), item.get("fromString"))
                resolver.observe_changelog(item.get("to"), item.get("toString"))
    return resolver
