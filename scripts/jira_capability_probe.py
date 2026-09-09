"""Read-only Jira Data Center/ScriptRunner release-gate probe."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.sprint_viewer_service import SprintViewerService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board-id", type=int, required=True)
    parser.add_argument("--sprint-id", type=int, required=True)
    args = parser.parse_args()
    base_url = os.environ.get("JIRA_BASE_URL", "").strip()
    pat = os.environ.get("JIRA_PAT", "").strip()
    if not base_url or not pat:
        parser.error("JIRA_BASE_URL and JIRA_PAT must be supplied through the environment")
    service = SprintViewerService(
        base_url,
        story_points_field=os.environ.get("JIRA_STORY_POINTS_FIELD", "customfield_10106"),
        application_field=os.environ.get("JIRA_APPLICATION_FIELD", "customfield_11700"),
        epic_link_field=os.environ.get("JIRA_EPIC_LINK_FIELD", "customfield_10100"),
    )
    result = {
        "probe": "read_only",
        "board_sprint_pagination": False,
        "core_issue_pagination": False,
        "metric_categories": {},
    }
    try:
        sprints = service.fetch_closed_sprints_for_board(args.board_id, pat)
        result["board_sprint_pagination"] = any(
            int(item.get("id")) == args.sprint_id for item in sprints if item.get("id")
        )
        issues = service.fetch_all_issues_for_sprint(args.sprint_id, pat)
        result["core_issue_pagination"] = issues["total"] == len(issues["issues"])
        metrics = service.compute_sprint_metrics_parallel(
            args.board_id, args.sprint_id, pat, total_sp=0, total_count=0
        )
        result["metric_categories"] = {
            "original_commitment": "original_commitment_count" in metrics,
            "completed_original": "completed_original_count" in metrics,
            "total_completed": "total_completed_count" in metrics,
            "added_scope": "added_scope_count" in metrics,
            "removed_scope": "removed_scope_count" in metrics,
        }
        print(json.dumps(result, sort_keys=True))
        return 0 if all(result["metric_categories"].values()) and result["board_sprint_pagination"] else 2
    finally:
        service._client.close()


if __name__ == "__main__":
    raise SystemExit(main())
