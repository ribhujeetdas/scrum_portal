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

