#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Jira Data Center L2 Updater (PAT / Bearer)
------------------------------------------
- Auth: Data Center PAT via Authorization: Bearer <token>
- API: /rest/api/2
- Assignee: set by "name" (DC usernames)

Logic:
1) Inspect PBCFB issue components (fields.components[].name) to select rule:
   - if "migration" or "exit": customfield_16400="OP3979 - 2026 DCMS Application Migrations and Modernization",
                               customfield_10707="PRJ0030408"
   - elif "CTB":               customfield_16400="OP3459 Technology demand | BOT",
                               customfield_10707="PRJ0030314"
   - elif "RTB":               do not modify these two
   - else:                     do not modify these two

2) Always for L2:
   - summary: "TCI | <existing> | <PBCFB-xxx> | <TeamName>"
     TeamName: PKLGX -> "CheckMates"; PBGXJ -> "Captors"; others -> error
   - Create "relates to" link between L2 and PBCFB
   - assignee: PKLGX -> K109707; PBGXJ -> K117771 (usernames)

Run:
  export JIRA_BASE_URL="https://jira.company.com"
  export JIRA_PAT="your_pat"
  python jira_l2_updater_dc.py --pbcfb PBCFB-123 --l2 PKLGX-456
"""

from __future__ import annotations
import argparse
import os
import sys
import time
import json
import re
from typing import Any, Dict, Optional, List
import requests
from dataclasses import dataclass

# ---------- Configurable constants ----------
TEAM_BY_PROJECT = {
    "PKLGX": "CheckMates",
    "PBGXJ": "Captors",
}

ASSIGNEE_BY_PROJECT = {
    "PKLGX": "K109707",  # DC username
    "PBGXJ": "K117771",  # DC username
}

FIELD_OUTPUT_ID = "customfield_16400"
FIELD_PROJECT_ID = "customfield_10707"

CTB_OUTPUT_VALUE = "OP3459 Technology demand | BOT"
CTB_PROJECT_VALUE = "PRJ0030314"

MIG_OUTPUT_VALUE = "OP3979 - 2026 DCMS Application Migrations and Modernization"
MIG_PROJECT_VALUE = "PRJ0030408"

SUMMARY_PREFIX = "TCI"
SUMMARY_SEPARATOR = " | "


@dataclass
class JiraAuth:
    base_url: str
    pat: str  # Data Center Personal Access Token


class JiraClient:
    def __init__(self, auth: JiraAuth, dry_run: bool = False):
        self.auth = auth
        self.dry_run = dry_run

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth.pat}",
        })
        self.api_base = f"{auth.base_url.rstrip('/')}/rest/api/2"

    # ---------------- Utilities ----------------
    def _url(self, path: str) -> str:
        return f"{self.api_base}{path}"

    def _req(self, method: str, path: str, **kwargs) -> requests.Response:
        url = self._url(path)
        for attempt in range(5):
            resp = self.session.request(method, url, timeout=30, **kwargs)
            if resp.status_code in (429, 502, 503, 504):
                wait = min(2 ** attempt, 16)
                print(
                    f"[JiraClient] {method} {url} -> {resp.status_code}; retry in {wait}s")
                time.sleep(wait)
                continue
            return resp
        return resp

    # ---------------- Core API -----------------
    def get_issue(self, issue_id_or_key: str, fields: Optional[List[str]] = None) -> Dict[str, Any]:
        query = ""
        if fields:
            query = "?fields=" + ",".join(fields)
        resp = self._req("GET", f"/issue/{issue_id_or_key}{query}")
        if resp.status_code == 404:
            raise RuntimeError(f"Issue not found: {issue_id_or_key}")
        resp.raise_for_status()
        return resp.json()

    def update_issue_fields(self, issue_key: str, fields: Dict[str, Any]) -> None:
        payload = {"fields": fields}
        if self.dry_run:
            print(
                f"[DRY-RUN] PUT /issue/{issue_key} -> {json.dumps(payload, indent=2, ensure_ascii=False)}")
            return
        resp = self._req("PUT", f"/issue/{issue_key}", json=payload)
        if resp.status_code not in (200, 204):
            raise RuntimeError(
                f"Failed to update {issue_key}: {resp.status_code} {resp.text}")

    def get_link_types(self) -> List[Dict[str, Any]]:
        resp = self._req("GET", "/issueLinkType")
        resp.raise_for_status()
        data = resp.json()
        return data.get("issueLinkTypes", data.get("linkTypes", []))

    def create_issue_link(self, inward_key: str, outward_key: str, link_type_name: str) -> None:
        payload = {
            "type": {"name": link_type_name},
            "inwardIssue": {"key": inward_key},
            "outwardIssue": {"key": outward_key},
        }
        if self.dry_run:
            print(
                f"[DRY-RUN] POST /issueLink -> {json.dumps(payload, indent=2, ensure_ascii=False)}")
            return
        resp = self._req("POST", "/issueLink", json=payload)
        if resp.status_code in (200, 201, 204):
            return
        # 400 when the link already exists or validation issue
        if resp.status_code == 400 and "already exists" in resp.text.lower():
            print(
                f"[INFO] Link already exists: {inward_key} <-> {outward_key} ({link_type_name})")
            return
        raise RuntimeError(
            f"Failed to create issue link: {resp.status_code} {resp.text}")

    def set_assignee(self, issue_key: str, username: str) -> None:
        """
        Data Center: assign by 'name' (username).
        """
        payload = {"name": username}
        if self.dry_run:
            print(f"[DRY-RUN] PUT /issue/{issue_key}/assignee -> {payload}")
            return
        resp = self._req("PUT", f"/issue/{issue_key}/assignee", json=payload)
        if resp.status_code not in (204, 200):
            raise RuntimeError(
                f"Failed to set assignee on {issue_key} to '{username}': {resp.status_code} {resp.text}")


# --------------- Business Logic ----------------

def detect_rule_from_components(components: List[Dict[str, Any]]) -> str:
    """
    Evaluate component names (case-insensitive) and return one of:
    'migration', 'ctb', 'rtb', 'none'
    Priority: migration/exit > ctb > rtb > none
    """
    names = [c.get("name", "") for c in (components or [])]
    blob = " ".join(names).lower()
    if any(k in blob for k in ("migration", "exit")):
        return "migration"
    if "ctb" in blob:
        return "ctb"
    if "rtb" in blob:
        return "rtb"
    return "none"


def ensure_summary_format(existing_summary: str, pbcfb_key: str, team_name: str) -> str:
    """
    Build: "TCI | <existing> | <PBCFB-xxx> | <TeamName>"
    Make idempotent by removing a previous appended suffix/prefix if present.
    """
    ex = (existing_summary or "").strip()

    # Strip leading "TCI | " if already present
    if ex.lower().startswith("tci | "):
        ex = ex[len("TCI | "):]

    # Strip trailing " | PBCFB-<digits> | <TeamName>"
    tail = re.compile(
        r"\s*\|\s*PBCFB-\d+\s*\|\s*(CheckMates|Captors)\s*$", re.IGNORECASE)
    ex = tail.sub("", ex).strip()

    return " | ".join([SUMMARY_PREFIX, ex, pbcfb_key.upper(), team_name])


def parse_project_key(issue_key: str) -> str:
    return issue_key.split("-")[0].upper()


def resolve_issue_key(client: JiraClient, issue_id_or_key: str) -> str:
    data = client.get_issue(issue_id_or_key, fields=["key"])
    return data["key"]


def choose_relates_link_name(client: JiraClient) -> str:
    types = client.get_link_types()
    candidates = ["Relates", "relates to", "Related", "Relate"]
    for t in types:
        name = t.get("name", "")
        if name in candidates or name.lower() in (c.lower() for c in candidates):
            return t["name"]
        inward = (t.get("inward", "") or "").lower()
        outward = (t.get("outward", "") or "").lower()
        if "relate" in inward or "relate" in outward:
            return t["name"]
    return types[0]["name"] if types else "Relates"


def main():
    parser = argparse.ArgumentParser(
        description="Update L2 Jira issue (Data Center) based on PBCFB components/title.")
    parser.add_argument("--pbcfb", required=True,
                        help="PBCFB issue id or key (e.g., PBCFB-123 or 100123)")
    parser.add_argument("--l2", required=True,
                        help="L2 issue key or id (e.g., PKLGX-456)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without making changes.")
    args = parser.parse_args()

    base_url = os.getenv("JIRA_BASE_URL")
    pat = os.getenv("JIRA_PAT")

    if not base_url:
        print("ERROR: Set JIRA_BASE_URL environment variable.")
        sys.exit(1)
    if not pat:
        print("ERROR: Set JIRA_PAT environment variable (Data Center PAT).")
        sys.exit(1)

    client = JiraClient(
        JiraAuth(base_url=base_url, pat=pat), dry_run=args.dry_run)

    # Resolve canonical keys
    pbcfb_key = resolve_issue_key(client, args.pbcfb)
    l2_key = resolve_issue_key(client, args.l2)

    # Fetch PBCFB components
    pbcfb_issue = client.get_issue(pbcfb_key, fields=["key", "components"])
    components = pbcfb_issue.get("fields", {}).get("components", []) or []
    rule = detect_rule_from_components(components)
    print(
        f"[INFO] PBCFB {pbcfb_key} components: {[c.get('name') for c in components]} -> rule='{rule}'")

    # Fetch L2 summary & project
    l2_issue = client.get_issue(l2_key, fields=["summary", "project"])
    existing_summary = l2_issue.get("fields", {}).get("summary", "")
    project_key = (l2_issue.get("fields", {}).get("project", {})
                   or {}).get("key") or parse_project_key(l2_key)
    project_key = project_key.upper()

    if project_key not in TEAM_BY_PROJECT:
        raise RuntimeError(
            f"Unsupported L2 project '{project_key}'. Expected one of: {list(TEAM_BY_PROJECT.keys())}")

    team_name = TEAM_BY_PROJECT[project_key]
    assignee_username = ASSIGNEE_BY_PROJECT[project_key]

    # Build new summary
    new_summary = ensure_summary_format(existing_summary, pbcfb_key, team_name)

    # Prepare field updates
    fields_update: Dict[str, Any] = {"summary": new_summary}

    if rule == "migration":
        fields_update[FIELD_OUTPUT_ID] = MIG_OUTPUT_VALUE
        fields_update[FIELD_PROJECT_ID] = MIG_PROJECT_VALUE
    elif rule == "ctb":
        fields_update[FIELD_OUTPUT_ID] = CTB_OUTPUT_VALUE
        fields_update[FIELD_PROJECT_ID] = CTB_PROJECT_VALUE
    elif rule == "rtb":
        # no changes to these two fields
        pass
    else:
        print(
            "[INFO] No recognized keywords in components -> leaving custom fields unchanged.")

    # Update fields
    client.update_issue_fields(l2_key, fields_update)
    print(
        f"[INFO] Updated {l2_key} fields: {json.dumps(fields_update, indent=2, ensure_ascii=False)}")

    # Link issues with "Relates"
    link_name = choose_relates_link_name(client)
    client.create_issue_link(
        inward_key=l2_key, outward_key=pbcfb_key, link_type_name=link_name)
    print(
        f"[INFO] Ensured link '{link_name}' between {l2_key} and {pbcfb_key}")

    # Assign L2 by username
    client.set_assignee(l2_key, assignee_username)
    print(f"[INFO] Assigned {l2_key} to '{assignee_username}'")

    print("[DONE]")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(2)
