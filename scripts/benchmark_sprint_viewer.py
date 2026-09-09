"""Repeatable local CPU baseline for Sprint Viewer transforms.

This is not an end-user latency claim. Production acceptance must also record
Jira, queue, authorization, SQLite, and browser timings from staging.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.sprint_viewer_service import SprintViewerService


def fixture(size: int) -> list[dict]:
    return [
        {
            "issue_id": str(index),
            "issue_key": f"ABC-{index}",
            "assignee_eid": f"E{index % 20:03d}",
            "assignee_name": f"User {index % 20:03d}",
            "principal_id": f"key:USER{index % 20:03d}",
            "story_points": float(index % 8),
            "issue_type": "Bug" if index % 7 == 0 else "Story",
            "is_subtask": False,
            "relevant_comment_count": index % 3,
        }
        for index in range(size)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=20)
    args = parser.parse_args()
    service = SprintViewerService("https://jira.invalid")
    for size in (50, 250, 1000):
        values = fixture(size)
        samples = []
        for _ in range(args.runs):
            started = time.perf_counter()
            service.group_issues_by_assignee(values)
            service.compute_issue_quality_stats(values)
            service.compute_work_type_mix(values)
            samples.append((time.perf_counter() - started) * 1000)
        ordered = sorted(samples)
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
        print(f"tickets={size} median_ms={statistics.median(samples):.3f} p95_ms={p95:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
