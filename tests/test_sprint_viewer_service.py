from app.services.sprint_viewer_service import SprintViewerService


def test_quality_stats_use_normalized_story_points():
    stats = SprintViewerService.compute_issue_quality_stats(
        [
            {
                "story_points": 3,
                "issue_type": "Bug",
                "assignee_eid": "E123",
                "comment_total": 1,
            },
            {
                "story_points": None,
                "issue_type": "Story",
                "assignee_eid": "UNASSIGNED",
                "comment_total": 0,
            },
        ]
    )

    assert stats["bug_count"] == 1
    assert stats["bug_sp"] == 3.0
    assert stats["unestimated_count"] == 1
    assert stats["unassigned_count"] == 1
    assert stats["zero_comment_count"] == 1


def test_quality_stats_support_raw_jira_story_point_field():
    stats = SprintViewerService.compute_issue_quality_stats(
        [
            {
                "customfield_10106": 5,
                "issue_type": "Bug",
                "assignee_eid": "E456",
                "comment_total": 0,
            }
        ]
    )

    assert stats["bug_count"] == 1
    assert stats["bug_sp"] == 5.0
    assert stats["unestimated_count"] == 0


def test_scrum_metrics_use_completed_original_for_predictability():
    metrics = SprintViewerService.build_scrum_metrics(
        {
            "original_commitment": {"sp": 40, "count": 10},
            "completed_original": {"sp": 32, "count": 8},
            "total_completed": {"sp": 44, "count": 11},
            "added_scope": {"sp": 12, "count": 3, "keys": ["ABC-9"]},
            "removed_scope": {"sp": 4, "count": 1},
        }
    )

    assert metrics["commitment_predictability_pct"] == 80.0
    assert metrics["total_completed_sp"] == 44.0
    assert metrics["completed_added_sp"] == 12.0
    assert metrics["carryover_sp"] == 4.0
    assert metrics["scope_net_sp"] == 8.0
    assert metrics["scope_added_keys"] == ["ABC-9"]


def test_relevant_comments_count_assignee_or_sprint_team_before_sprint_end():
    issues = [
        {
            "issue_key": "ABC-1",
            "story_points": 3,
            "issue_type": "Story",
            "assignee_eid": "E1",
            "comment_total": 4,
            "comments": [
                {"author_eid": "E1", "created": "2026-01-10T10:00:00.000+0000"},
                {"author_eid": "E2", "created": "2026-01-10T11:00:00.000+0000"},
                {"author_eid": "OUTSIDER", "created": "2026-01-10T12:00:00.000+0000"},
                {"author_eid": "E2", "created": "2026-01-20T12:00:00.000+0000"},
            ],
        },
        {
            "issue_key": "ABC-2",
            "story_points": 5,
            "issue_type": "Bug",
            "assignee_eid": "E2",
            "comment_total": 0,
            "comments": [],
        },
    ]

    SprintViewerService.apply_relevant_comment_counts(
        issues, sprint_complete_date="2026-01-15T00:00:00.000+0000"
    )
    stats = SprintViewerService.compute_issue_quality_stats(issues)

    assert issues[0]["relevant_comment_count"] == 2
    assert issues[1]["relevant_comment_count"] == 0
    assert stats["relevant_comment_count"] == 2
    assert stats["zero_relevant_comment_count"] == 1


def test_historical_field_reconstruction_uses_value_at_sprint_end():
    issue = {
        "fields": {
            "summary": "Story",
            "customfield_10106": 8,
            "issuetype": {"name": "Story", "subtask": False},
            "status": {"name": "In Progress"},
            "assignee": {"name": "E2", "displayName": "New Assignee"},
            "comment": {"total": 0, "comments": []},
        },
        "changelog": {
            "histories": [
                {
                    "created": "2026-01-12T10:00:00.000+0000",
                    "items": [
                        {"field": "status", "fromString": "To Do", "toString": "In Progress"},
                        {"field": "assignee", "fromString": "Old Assignee", "toString": "New Assignee", "from": "E1", "to": "E2"},
                        {"field": "Story Points", "fromString": "5", "toString": "8"},
                    ],
                }
            ]
        },
    }

    extracted = SprintViewerService.extract_issue_fields(
        issue, sprint_complete_date="2026-01-10T00:00:00.000+0000"
    )

    assert extracted["status"] == "To Do"
    assert extracted["assignee_eid"] == "E1"
    assert extracted["story_points"] == 5.0
    assert extracted["historical_fallback"] is False
