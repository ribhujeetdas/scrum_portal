from __future__ import annotations

from typing import Any


def _number(value: Any, kind: type[float] | type[int]):
    try:
        return kind(value or 0)
    except (TypeError, ValueError):
        return kind(0)


def _percentage(numerator: float, denominator: float) -> float:
    return (numerator / denominator) * 100.0 if denominator > 0 else 0.0


def build_scrum_metrics(results: dict[str, dict]) -> dict:
    """Pure Scrum metric transformation, independent of Flask, HTTP and persistence."""
    original = results.get("original_commitment", {})
    completed_original = results.get("completed_original", {})
    total_completed = results.get("total_completed", {})
    added = results.get("added_scope", {})
    removed = results.get("removed_scope", {})

    original_sp = _number(original.get("sp"), float)
    original_count = _number(original.get("count"), int)
    completed_original_sp = _number(completed_original.get("sp"), float)
    completed_original_count = _number(completed_original.get("count"), int)
    total_completed_sp = _number(total_completed.get("sp"), float)
    total_completed_count = _number(total_completed.get("count"), int)
    added_sp = _number(added.get("sp"), float)
    added_count = _number(added.get("count"), int)
    removed_sp = _number(removed.get("sp"), float)
    removed_count = _number(removed.get("count"), int)

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
        "commitment_predictability_pct": round(_percentage(completed_original_sp, original_sp), 1),
        "total_delivery_vs_commitment_pct": round(_percentage(total_completed_sp, original_sp), 1),
        "added_scope_pct": round(_percentage(added_sp, original_sp), 1),
        "removed_scope_pct": round(_percentage(removed_sp, original_sp), 1),
        "scope_change_pct": round(_percentage(added_sp + removed_sp, original_sp), 1),
        "scope_added_keys": added.get("keys") or [],
    }
    output.update(
        {
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
            "spill_pct": round(_percentage(carryover_sp, original_sp), 1),
            "scope_pct": output["added_scope_pct"],
            "spill_red": _percentage(carryover_sp, original_sp) > 20.0,
            "scope_red": output["added_scope_pct"] > 20.0,
        }
    )
    return output
