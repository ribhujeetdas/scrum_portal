from __future__ import annotations

import math
from typing import Any, Mapping


METRIC_CATEGORIES = (
    "original_commitment",
    "completed_original",
    "total_completed",
    "added_scope",
    "removed_scope",
)


def metric_queries(board_id: int, sprint_id: int) -> dict[str, dict[str, Any]]:
    return {
        "original_commitment": {
            "jql": (
                f"(issueFunction in completeInSprint({board_id}, {sprint_id}) "
                f"OR issueFunction in incompleteInSprint({board_id},{sprint_id}) "
                f"OR issueFunction in removedAfterSprintStart({board_id},{sprint_id})) "
                f"AND issueFunction NOT IN addedAfterSprintStart({board_id},{sprint_id}) "
                "AND issuetype IN standardIssueTypes() ORDER BY id ASC"
            ),
            "capture_keys": False,
        },
        "completed_original": {
            "jql": f"issueFunction in completeInSprint({board_id}, {sprint_id}) AND issueFunction NOT IN addedAfterSprintStart({board_id},{sprint_id}) AND issuetype IN standardIssueTypes() ORDER BY id ASC",
            "capture_keys": False,
        },
        "total_completed": {
            "jql": f"issueFunction in completeInSprint({board_id}, {sprint_id}) AND issuetype IN standardIssueTypes() ORDER BY id ASC",
            "capture_keys": False,
        },
        "added_scope": {
            "jql": f"issueFunction in addedAfterSprintStart({board_id},{sprint_id}) AND issuetype IN standardIssueTypes() ORDER BY id ASC",
            "capture_keys": True,
        },
        "removed_scope": {
            "jql": f"issueFunction in removedAfterSprintStart({board_id},{sprint_id}) AND issuetype IN standardIssueTypes() ORDER BY id ASC",
            "capture_keys": False,
        },
    }


def _finite_number(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def build_scrum_metrics(results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    values = {name: results.get(name, {}) for name in METRIC_CATEGORIES}
    original_sp = _finite_number(values["original_commitment"].get("sp", 0))
    original_count = int(values["original_commitment"].get("count", 0))
    completed_original_sp = _finite_number(values["completed_original"].get("sp", 0))
    completed_original_count = int(values["completed_original"].get("count", 0))
    total_completed_sp = _finite_number(values["total_completed"].get("sp", 0))
    total_completed_count = int(values["total_completed"].get("count", 0))
    added_sp = _finite_number(values["added_scope"].get("sp", 0))
    added_count = int(values["added_scope"].get("count", 0))
    removed_sp = _finite_number(values["removed_scope"].get("sp", 0))
    removed_count = int(values["removed_scope"].get("count", 0))

    def pct(numerator: float, denominator: float) -> float:
        return numerator / denominator * 100.0 if denominator > 0 else 0.0

    completed_added_sp = max(0.0, total_completed_sp - completed_original_sp)
    completed_added_count = max(0, total_completed_count - completed_original_count)
    carryover_sp = max(0.0, original_sp - completed_original_sp - removed_sp)
    carryover_count = max(0, original_count - completed_original_count - removed_count)
    output = {
        "original_commitment_sp": round(original_sp, 2),
        "original_commitment_count": original_count,
        "completed_original_sp": round(completed_original_sp, 2),
        "completed_original_count": completed_original_count,
        "completed_added_sp": round(completed_added_sp, 2),
        "completed_added_count": completed_added_count,
        "total_completed_sp": round(total_completed_sp, 2),
        "total_completed_count": total_completed_count,
        "added_scope_sp": round(added_sp, 2),
        "added_scope_count": added_count,
        "removed_scope_sp": round(removed_sp, 2),
        "removed_scope_count": removed_count,
        "carryover_sp": round(carryover_sp, 2),
        "carryover_count": carryover_count,
        "scope_net_sp": round(added_sp - removed_sp, 2),
        "scope_net_count": added_count - removed_count,
        "commitment_predictability_pct": round(pct(completed_original_sp, original_sp), 1),
        "total_delivery_vs_commitment_pct": round(pct(total_completed_sp, original_sp), 1),
        "added_scope_pct": round(pct(added_sp, original_sp), 1),
        "removed_scope_pct": round(pct(removed_sp, original_sp), 1),
        "scope_change_pct": round(pct(added_sp + removed_sp, original_sp), 1),
        "scope_added_keys": list(values["added_scope"].get("keys") or []),
        "time_basis": "Jira points at collection time",
        "calculation_version": 1,
    }
    output.update({
        "committed_sp": output["original_commitment_sp"],
        "committed_count": output["original_commitment_count"],
        "delivered_sp": output["total_completed_sp"],
        "delivered_count": output["total_completed_count"],
        "spillover_sp": output["carryover_sp"],
        "spillover_count": output["carryover_count"],
        "scope_added_sp": output["added_scope_sp"],
        "scope_added_count": output["added_scope_count"],
        "descope_sp": output["removed_scope_sp"],
        "descope_count": output["removed_scope_count"],
        "predictability_pct": output["commitment_predictability_pct"],
        "spill_pct": round(pct(carryover_sp, original_sp), 1),
        "scope_pct": output["added_scope_pct"],
        "spill_red": pct(carryover_sp, original_sp) > 20.0,
        "scope_red": output["added_scope_pct"] > 20.0,
    })
    return output
