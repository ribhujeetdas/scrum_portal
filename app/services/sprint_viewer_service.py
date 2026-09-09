# app/services/sprint_viewer_service.py
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Optional, Set, Dict, Any, List

from flask import current_app, has_app_context

from app.core.http_client import ExternalHttpClient, ExternalServiceError
from app.features.automation.sprint_viewer.calculations import (
    build_scrum_metrics as calculate_scrum_metrics,
    metric_queries,
)
from app.integrations.jira.pagination import JiraPaginationError, collect_offset_pages
from app.integrations.jira.identity import JiraIdentityResolver, build_identity_resolver


class SprintViewerServiceError(Exception):
    pass


class SprintViewerService:
    """
    Jira DC endpoints used:
    - GET /rest/agile/1.0/board/{boardId}/sprint
    - GET /rest/agile/1.0/sprint/{sprintId}/issue
    - GET /rest/api/2/search (for JQL metrics)
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 30,
        http_client: ExternalHttpClient | None = None,
        metrics_max_workers: int = 5,
        story_points_field: str = "customfield_10106",
        application_field: str = "customfield_11700",
        epic_link_field: str = "customfield_10100",
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds
        self.metrics_max_workers = max(1, min(int(metrics_max_workers or 5), 16))
        self.story_points_field = story_points_field
        self.application_field = application_field
        self.epic_link_field = epic_link_field
        if not self.base_url:
            raise ValueError("JIRA_BASE_URL is missing.")
        self._client = http_client or self._new_client()

    def normalize_configured_fields(self, issue: dict) -> dict:
        """Copy configured Jira fields into the stable calculation schema."""
        fields = issue.get("fields") or {}
        fields["customfield_10106"] = fields.get(self.story_points_field)
        fields["customfield_11700"] = fields.get(self.application_field)
        fields["customfield_10100"] = fields.get(self.epic_link_field)
        issue["fields"] = fields
        return issue

    # ---------------------------
    # Trace helpers (config-driven)
    # ---------------------------
    def _trace(self, msg: str, *args) -> None:
        # TRACE_SPRINT_VIEWER controls internal step tracing
        if has_app_context() and current_app.config.get("TRACE_SPRINT_VIEWER", False):
            current_app.logger.debug(msg, *args)

    def _trace_jql(self, msg: str, *args) -> None:
        # TRACE_JIRA_JQL controls JQL-specific tracing (can be noisier)
        if has_app_context() and current_app.config.get("TRACE_JIRA_JQL", False):
            current_app.logger.debug(msg, *args)

    # ---------------------------
    # HTTP client / headers
    # ---------------------------
    def _new_client(self) -> ExternalHttpClient:
        """
        Create a client with retry policy.
        Note: create a new one per thread for metrics.
        """
        return ExternalHttpClient(
            "jira", self.base_url, timeout_seconds=self.timeout
        )

    def _headers(self, pat: str) -> dict:
        # Do NOT log this header; it contains bearer token
        return {
            "Authorization": f"Bearer {pat}",
            "Accept": "application/json",
        }

    @staticmethod
    def _year_from_start_date(start_date: Optional[str]) -> Optional[int]:
        if not start_date:
            return None
        try:
            return int(start_date[:4])
        except Exception:
            return None

    @staticmethod
    def _parse_jira_datetime(value: Optional[str]):
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+0000"
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None

    @staticmethod
    def _comment_author_eid(comment: dict) -> str:
        author = comment.get("author") or {}
        return str(
            author.get("name")
            or author.get("key")
            or author.get("accountId")
            or author.get("displayName")
            or ""
        ).strip()

    @staticmethod
    def _comment_slim(comment: dict, resolver: JiraIdentityResolver | None = None) -> dict:
        author = comment.get("author") or {}
        return {
            "author_eid": SprintViewerService._comment_author_eid(comment),
            "principal_id": resolver.resolve(author) if resolver else None,
            "created": comment.get("created"),
        }

    @staticmethod
    def _item_field(item: dict) -> str:
        return str(item.get("field") or item.get("fieldId") or "").strip().lower()

    @staticmethod
    def _safe_story_points(value: Any) -> float | None:
        if value is None or str(value).strip() == "":
            return None
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _reconstruct_at_sprint_end(
        issue: dict,
        values: dict,
        sprint_complete_date: Optional[str],
        resolver: JiraIdentityResolver | None = None,
    ) -> tuple[dict, bool]:
        cutoff = SprintViewerService._parse_jira_datetime(sprint_complete_date)
        if cutoff is None:
            return values, False

        histories = ((issue.get("changelog") or {}).get("histories") or [])
        if not histories:
            changelog = issue.get("changelog")
            if isinstance(changelog, dict) and changelog.get("total") == 0:
                return values, False
            return values, True

        reconstructed = dict(values)
        for history in sorted(
            histories,
            key=lambda h: (
                SprintViewerService._parse_jira_datetime(h.get("created"))
                or datetime.min.replace(tzinfo=timezone.utc)
            ),
            reverse=True,
        ):
            changed_at = SprintViewerService._parse_jira_datetime(history.get("created"))
            if changed_at is None or changed_at <= cutoff:
                continue

            for item in history.get("items") or []:
                field = SprintViewerService._item_field(item)
                if field == "status":
                    reconstructed["status"] = item.get("fromString")
                elif field == "assignee":
                    previous_id = item.get("from")
                    previous_label = item.get("fromString")
                    if previous_id is None and previous_label is None:
                        reconstructed["assignee_eid"] = "UNASSIGNED"
                        reconstructed["assignee_name"] = "Unassigned"
                        reconstructed["principal_id"] = "unassigned"
                    else:
                        reconstructed["assignee_eid"] = str(previous_id or previous_label).strip()
                        reconstructed["assignee_name"] = str(previous_label or previous_id).strip()
                        reconstructed["principal_id"] = (
                            resolver.observe_changelog(previous_id, previous_label)
                            if resolver
                            else f"key:{str(previous_id or previous_label).strip()}"
                        )
                elif field in {"story points", "customfield_10106"}:
                    raw_previous = item.get("fromString") if "fromString" in item else item.get("from")
                    sp = SprintViewerService._safe_story_points(raw_previous)
                    reconstructed["story_points"] = sp

        return reconstructed, False

    @staticmethod
    def _issue_has_multiple_sprints(issue: dict) -> bool:
        sprint_ids: set[str] = set()
        for history in (issue.get("changelog") or {}).get("histories") or []:
            for item in history.get("items") or []:
                field = SprintViewerService._item_field(item)
                if field != "sprint":
                    continue
                for key in ("from", "to", "fromString", "toString"):
                    value = item.get(key)
                    if not value:
                        continue
                    sprint_ids.update(re.findall(r"id=(\d+)", str(value)))
                    if str(value).isdigit():
                        sprint_ids.add(str(value))
        return len(sprint_ids) > 1

    # ---------------------------
    # Sprint list
    # ---------------------------
    def fetch_closed_sprints_for_board(self, board_id: int, pat: str) -> list[dict]:
        current_year = datetime.now().year
        allowed_years = {current_year, current_year - 1}
        max_results = 50

        self._trace("Sprints start board_id=%s maxResults=%s",
                    board_id, max_results)

        def fetch_page(start_at: int, page_size: int):
            params = {"startAt": start_at, "maxResults": page_size, "state": "closed"}
            try:
                return self._client.get_json(
                    f"/rest/agile/1.0/board/{board_id}/sprint",
                    headers=self._headers(pat),
                    params=params,
                )
            except ExternalServiceError as exc:
                self._raise_sprint_api_error(
                    exc,
                    network_message="Network error fetching sprints",
                    invalid_json_message="Invalid JSON returned by sprint API.",
                    generic_message="Sprint API error",
                    unauthorized_message="Unauthorized (401) while fetching sprints. Check PAT.",
                    forbidden_message="Forbidden (403) while fetching sprints.",
                )

        try:
            source_sprints = collect_offset_pages(
                fetch_page,
                collection_key="values",
                requested_page_size=max_results,
                identity=lambda sprint: str(sprint.get("id")) if sprint.get("id") is not None else None,
            )
        except JiraPaginationError as exc:
            raise SprintViewerServiceError(f"Sprint pagination incomplete: {exc}") from exc

        all_sprints = [
            sprint
            for sprint in source_sprints
            if (sprint.get("state") or "").lower() == "closed"
            and self._year_from_start_date(sprint.get("startDate")) in allowed_years
        ]

        self._trace("Sprints done board_id=%s final_count=%s",
                    board_id, len(all_sprints))
        return all_sprints

    # ---------------------------
    # Sprint issues (pagination)
    # ---------------------------
    def fetch_all_issues_for_sprint(
        self, sprint_id: int, pat: str, *, hydrate_comments: bool = False
    ) -> dict:
        max_results = 50

        fields = [
            "summary",
            self.story_points_field,
            "issuetype",
            "status",
            self.application_field,
            self.epic_link_field,
            "epic",
            "assignee",
            "parent",
            "project",
            "updated",
        ]
        if hydrate_comments:
            fields.append("comment")

        self._trace("SprintIssues start sprint_id=%s maxResults=%s",
                    sprint_id, max_results)

        def fetch_page(start_at: int, page_size: int):
            params = {
                "startAt": start_at,
                "maxResults": page_size,
                "fields": ",".join(fields),
            }
            try:
                return self._client.get_json(
                    f"/rest/agile/1.0/sprint/{sprint_id}/issue",
                    headers=self._headers(pat),
                    params=params,
                )
            except ExternalServiceError as exc:
                self._raise_sprint_api_error(
                    exc,
                    network_message="Network error fetching sprint issues",
                    invalid_json_message="Invalid JSON returned by sprint issues API.",
                    generic_message="Sprint issues API error",
                    unauthorized_message="Unauthorized (401) while fetching sprint issues. Check PAT.",
                    forbidden_message="Forbidden (403) while fetching sprint issues.",
                )

        try:
            all_issues = collect_offset_pages(
                fetch_page,
                collection_key="issues",
                requested_page_size=max_results,
                identity=lambda issue: str(issue.get("id")) if issue.get("id") is not None else None,
            )
        except JiraPaginationError as exc:
            raise SprintViewerServiceError(f"Sprint issue pagination incomplete: {exc}") from exc
        all_issues = [self.normalize_configured_fields(issue) for issue in all_issues]
        if hydrate_comments:
            self._hydrate_incomplete_comments(all_issues, pat)
        final_total = len(all_issues)
        self._trace("SprintIssues done sprint_id=%s final_total=%s collected=%s",
                    sprint_id, final_total, len(all_issues))
        return {"total": final_total, "issues": all_issues}

    def _hydrate_incomplete_comments(self, issues: list[dict], pat: str) -> None:
        for issue in issues:
            fields = issue.get("fields") or {}
            comment_obj = fields.get("comment") or {}
            total = int(comment_obj.get("total") or 0)
            comments = comment_obj.get("comments") or []
            if total <= len(comments):
                continue
            issue_key = issue.get("key") or issue.get("id")
            if not issue_key:
                continue
            try:
                comment_obj["comments"] = self._fetch_all_comments_for_issue(str(issue_key), pat)
                fields["comment"] = comment_obj
                issue["fields"] = fields
            except SprintViewerServiceError:
                raise
            except Exception:
                continue

    def _fetch_all_comments_for_issue(self, issue_key: str, pat: str) -> list[dict]:
        all_comments: list[dict] = []
        start_at = 0
        max_results = 100
        while True:
            try:
                data = self._client.get_json(
                    f"/rest/api/2/issue/{issue_key}/comment",
                    headers=self._headers(pat),
                    params={"startAt": start_at, "maxResults": max_results},
                )
            except ExternalServiceError as exc:
                self._raise_sprint_api_error(
                    exc,
                    network_message="Network error fetching issue comments",
                    invalid_json_message="Invalid JSON returned by issue comments API.",
                    generic_message="Issue comments API error",
                    unauthorized_message="Unauthorized (401) while fetching issue comments. Check PAT.",
                    forbidden_message="Forbidden (403) while fetching issue comments.",
                )
            comments = data.get("comments") or []
            all_comments.extend(comments)
            total = int(data.get("total") or len(all_comments))
            if not comments or len(all_comments) >= total:
                break
            start_at += len(comments)
        return all_comments

    # ---------------------------
    # Field extraction / grouping
    # ---------------------------
    @staticmethod
    def extract_issue_fields(
        issue: dict,
        sprint_complete_date: Optional[str] = None,
        resolver: JiraIdentityResolver | None = None,
    ) -> dict:
        fields = issue.get("fields") or {}
        assignee = fields.get("assignee") or {}
        assignee_eid = assignee.get("name") or "UNASSIGNED"
        assignee_name = assignee.get("displayName") or "Unassigned"
        principal_id = resolver.resolve(assignee) if resolver else (
            f"key:{assignee.get('key')}" if assignee.get("key")
            else f"name:{assignee_eid}" if assignee_eid != "UNASSIGNED"
            else "unassigned"
        )

        issuetype = fields.get("issuetype") or {}
        status = fields.get("status") or {}
        is_subtask = bool(issuetype.get("subtask"))

        app_obj = fields.get("customfield_11700") or {}
        app_name = app_obj.get("value") or ""

        epic_obj = fields.get("epic") or {}
        epic_key = epic_obj.get("key") or (
            fields.get("customfield_10100") or "")
        epic_name = epic_obj.get("name") or ""

        comment_field_present = "comment" in fields
        comment_obj = fields.get("comment") or {}
        comment_total = comment_obj.get("total") if comment_field_present else None
        comments = [
            SprintViewerService._comment_slim(comment, resolver)
            for comment in (comment_obj.get("comments") or [])
        ]

        values = {
            "issue_id": issue.get("id"),
            "issue_key": issue.get("key"),
            "summary": fields.get("summary") or "",
            "story_points": fields.get("customfield_10106"),
            "issue_type": issuetype.get("name") or "",
            "is_subtask": is_subtask,
            "status": status.get("name") or "",
            "app_name": app_name,
            "feature_key": epic_key,
            "feature_name": epic_name,
            "comment_total": int(comment_total or 0) if comment_total is not None else None,
            "comments": comments,
            "relevant_comment_count": 0 if comment_field_present else None,
            "is_carryover": SprintViewerService._issue_has_multiple_sprints(issue),
            "assignee_eid": assignee_eid,
            "assignee_name": assignee_name,
            "principal_id": principal_id,
        }
        values, historical_fallback = SprintViewerService._reconstruct_at_sprint_end(
            issue, values, sprint_complete_date, resolver
        )
        values["historical_fallback"] = historical_fallback
        return values

    @staticmethod
    def _safe_float(v: Any) -> float:
        if v is None:
            return 0.0
        try:
            return float(v)
        except Exception:
            return 0.0

    @staticmethod
    def apply_relevant_comment_counts(extracted_issues: list[dict], sprint_complete_date: Optional[str] = None) -> None:
        team_principals = {
            str(issue.get("principal_id") or issue.get("assignee_eid") or "").strip()
            for issue in extracted_issues
            if issue.get("assignee_eid") and issue.get("assignee_eid") != "UNASSIGNED"
        }
        cutoff = SprintViewerService._parse_jira_datetime(sprint_complete_date)

        for issue in extracted_issues:
            if issue.get("comment_total") is None and not issue.get("comments"):
                issue["relevant_comment_count"] = None
                continue
            assignee_eid = str(issue.get("assignee_eid") or "").strip()
            allowed_authors = set(team_principals)
            principal_id = str(issue.get("principal_id") or assignee_eid).strip()
            if principal_id and assignee_eid != "UNASSIGNED":
                allowed_authors.add(principal_id)

            count = 0
            for comment in issue.get("comments") or []:
                author_identity = str(
                    comment.get("principal_id") or comment.get("author_eid") or ""
                ).strip()
                if author_identity not in allowed_authors:
                    continue
                created = SprintViewerService._parse_jira_datetime(comment.get("created"))
                if cutoff is not None and created is not None and created > cutoff:
                    continue
                count += 1
            issue["relevant_comment_count"] = count

    def group_issues_by_assignee(self, issues: list[dict]) -> list[dict]:
        """
        Enhanced grouping:
        - issue_count
        - sp_sum per assignee group
        """
        groups: dict[str, dict] = {}

        for it in issues:
            eid = it["assignee_eid"]
            group_key = str(it.get("principal_id") or eid)
            if group_key not in groups:
                groups[group_key] = {
                    "principal_id": group_key,
                    "assignee_eid": eid,
                    "assignee_name": it["assignee_name"],
                    "issues": [],
                    "issue_count": 0,
                    "sp_sum": 0.0,
                }

            groups[group_key]["issues"].append(it)
            groups[group_key]["issue_count"] += 1
            groups[group_key]["sp_sum"] += self._safe_float(it.get("story_points"))
            comment_count = it.get("relevant_comment_count")
            if comment_count is not None:
                groups[group_key]["relevant_comment_count"] = (
                    int(groups[group_key].get("relevant_comment_count") or 0)
                    + int(comment_count)
                )
            elif "relevant_comment_count" not in groups[group_key]:
                groups[group_key]["relevant_comment_count"] = None

        for g in groups.values():
            g["issues"].sort(key=lambda x: (x.get("issue_key") or ""))

        def group_sort_key(g: dict) -> tuple:
            name = g.get("assignee_name") or ""
            if g.get("assignee_eid") == "UNASSIGNED":
                return (1, name)
            return (0, name)

        result = list(groups.values())
        result.sort(key=group_sort_key)

        # final rounding
        for g in result:
            g["sp_sum"] = round(float(g["sp_sum"]), 2)

        return result

    @staticmethod
    def build_identity_resolver(issues: list[dict]) -> JiraIdentityResolver:
        return build_identity_resolver(issues)

    # ---------------------------
    # Total SP and helper stats
    # ---------------------------
    def sum_story_points(self, extracted_issues: list[dict]) -> float:
        total = 0.0
        for it in extracted_issues:
            total += self._safe_float(it.get("story_points"))
        return total

    @staticmethod
    def compute_issue_quality_stats(extracted_issues: list[dict]) -> dict:
        """
        Single-sprint perspective stats from already-fetched sprint issues.
        (No extra Jira calls.)
        """
        total_count = len(extracted_issues)
        unestimated_count = 0
        bug_count = 0
        bug_sp = 0.0
        unassigned_count = 0
        zero_comment_count = 0
        relevant_comment_count = 0
        zero_relevant_comment_count = 0
        comments_evaluated_count = 0
        carryover_count = 0
        carryover_sp = 0.0

        for it in extracted_issues:
            sp = it.get("story_points")
            if sp is None and "customfield_10106" in it:
                sp = it.get("customfield_10106")
            if sp is None or str(sp).strip() == "":
                unestimated_count += 1

            if (it.get("issue_type") or "").lower() == "bug":
                bug_count += 1
                try:
                    bug_sp += float(sp) if sp is not None else 0.0
                except Exception:
                    pass

            if (it.get("assignee_eid") or "") == "UNASSIGNED":
                unassigned_count += 1

            if it.get("comment_total") is not None:
                comments_evaluated_count += 1
                if int(it.get("comment_total") or 0) == 0:
                    zero_comment_count += 1
                relevant_comments = int(it.get("relevant_comment_count") or 0)
                relevant_comment_count += relevant_comments
                if relevant_comments == 0:
                    zero_relevant_comment_count += 1

            if it.get("is_carryover"):
                carryover_count += 1
                carryover_sp += SprintViewerService._safe_float(sp)

        def pct(n: float, d: float) -> float:
            if d and d > 0:
                return (n / d) * 100.0
            return 0.0

        return {
            "unestimated_count": unestimated_count,
            "unestimated_pct": round(pct(unestimated_count, total_count), 1),
            "bug_count": bug_count,
            "bug_sp": round(float(bug_sp), 2),
            "bug_pct": round(pct(bug_count, total_count), 1),
            "unassigned_count": unassigned_count,
            "unassigned_pct": round(pct(unassigned_count, total_count), 1),
            "comments_evaluated_count": comments_evaluated_count,
            "zero_comment_count": zero_comment_count if comments_evaluated_count else None,
            "zero_comment_pct": round(pct(zero_comment_count, comments_evaluated_count), 1) if comments_evaluated_count else None,
            "relevant_comment_count": relevant_comment_count if comments_evaluated_count else None,
            "zero_relevant_comment_count": zero_relevant_comment_count if comments_evaluated_count else None,
            "zero_relevant_comment_pct": round(pct(zero_relevant_comment_count, comments_evaluated_count), 1) if comments_evaluated_count else None,
            "carryover_count": carryover_count,
            "carryover_sp": round(float(carryover_sp), 2),
        }

    @staticmethod
    def compute_work_type_mix(extracted_issues: list[dict]) -> dict:
        def blank_bucket() -> dict:
            return {"count": 0, "pts": 0.0}

        overall: dict[str, dict] = {}
        by_assignee: dict[str, dict] = {}

        for issue in extracted_issues:
            issue_type = (issue.get("issue_type") or "Unknown").strip() or "Unknown"
            pts = SprintViewerService._safe_float(issue.get("story_points"))
            overall.setdefault(issue_type, blank_bucket())
            overall[issue_type]["count"] += 1
            overall[issue_type]["pts"] += pts

            assignee = issue.get("assignee_eid") or "UNASSIGNED"
            assignee_name = issue.get("assignee_name") or "Unassigned"
            assignee_key = str(issue.get("principal_id") or assignee)
            by_assignee.setdefault(
                assignee_key,
                {
                    "principal_id": assignee_key,
                    "assignee_eid": assignee,
                    "assignee_name": assignee_name,
                    "types": {},
                },
            )
            by_assignee[assignee_key]["types"].setdefault(issue_type, blank_bucket())
            by_assignee[assignee_key]["types"][issue_type]["count"] += 1
            by_assignee[assignee_key]["types"][issue_type]["pts"] += pts

        for bucket in overall.values():
            bucket["pts"] = round(bucket["pts"], 2)
        for assignee in by_assignee.values():
            for bucket in assignee["types"].values():
                bucket["pts"] = round(bucket["pts"], 2)

        return {
            "overall": dict(sorted(overall.items())),
            "by_assignee": sorted(by_assignee.values(), key=lambda row: row["assignee_name"]),
        }

    # ---------------------------
    # JQL Aggregation: SP + Count (+ optional keys)
    # ---------------------------
    def _aggregate_by_jql_with_client(
        self,
        client: ExternalHttpClient,
        jql: str,
        pat: str,
        capture_keys: bool = False,
    ) -> dict:
        max_results = 200

        jql_short = jql.replace("\n", " ").strip()
        if len(jql_short) > 180:
            jql_short = jql_short[:180] + "..."

        self._trace_jql("JQLAgg start maxResults=%s jql=%s", max_results, jql_short)

        def fetch_page(start_at: int, page_size: int):
            params = {
                "jql": jql,
                "startAt": start_at,
                "maxResults": page_size,
                "fields": f"id,key,{self.story_points_field},project,updated",
            }
            try:
                return client.get_json(
                    "/rest/api/2/search",
                    headers=self._headers(pat),
                    params=params,
                )
            except ExternalServiceError as exc:
                self._raise_sprint_api_error(
                    exc,
                    network_message="Network error running JQL search",
                    invalid_json_message="Invalid JSON returned by JQL search.",
                    generic_message="JQL search error",
                    unauthorized_message="Unauthorized (401) while running JQL search. Check PAT.",
                    forbidden_message="Forbidden (403) while running JQL search.",
                )

        try:
            issues = collect_offset_pages(
                fetch_page,
                collection_key="issues",
                requested_page_size=max_results,
                identity=lambda issue: str(issue.get("id")) if issue.get("id") is not None else None,
            )
        except JiraPaginationError as exc:
            raise SprintViewerServiceError(f"Metric pagination incomplete: {exc}") from exc

        total_sp = 0.0
        keys: Set[str] = set()
        memberships: list[dict] = []
        for issue in issues:
            fields = self.normalize_configured_fields(issue).get("fields") or {}
            raw_sp = fields.get("customfield_10106")
            point_value = self._safe_story_points(raw_sp)
            if point_value is not None and math.isfinite(point_value):
                total_sp += point_value
            if capture_keys and issue.get("key"):
                keys.add(str(issue["key"]))
            project = fields.get("project") or {}
            memberships.append({
                "issue_id": str(issue.get("id")),
                "issue_key": issue.get("key"),
                "project_id": project.get("id"),
                "project_key": project.get("key"),
                "story_points": point_value,
                "updated": fields.get("updated"),
            })

        out = {"sp": float(total_sp), "count": len(issues), "memberships": memberships}
        if capture_keys:
            out["keys"] = sorted(keys)
        self._trace_jql("JQLAgg done sp=%.2f count=%s jql=%s",
                        out["sp"], out["count"], jql_short)
        return out

    # ---------------------------
    # Metrics in parallel (SP + Count + scope_added keys)
    # ---------------------------
    @staticmethod
    def build_scrum_metrics(results: Dict[str, dict]) -> dict:
        return calculate_scrum_metrics(results)

    def compute_sprint_metrics_parallel(self, board_id: int, sprint_id: int, pat: str, total_sp: float, total_count: int) -> dict:
        jobs = metric_queries(board_id, sprint_id)

        self._trace("Metrics start board_id=%s sprint_id=%s total_sp=%.2f total_count=%s",
                    board_id, sprint_id, total_sp, total_count)

        results: Dict[str, dict] = {k: {"sp": 0.0, "count": 0} for k in jobs.keys()}

        for name, spec in jobs.items():
            agg = self._aggregate_by_jql_with_client(
                client=self._client,
                jql=spec["jql"],
                pat=pat,
                capture_keys=bool(spec.get("capture_keys", False)),
            )
            results[name] = agg
            self._trace("Metrics partial %s sp=%.2f count=%s", name, float(
                agg.get("sp", 0.0)), int(agg.get("count", 0)))
        out = self.build_scrum_metrics(results)

        self._trace("Metrics done board_id=%s sprint_id=%s result=%s",
                    board_id, sprint_id, out)
        return out

    @staticmethod
    def _raise_sprint_api_error(
        exc: ExternalServiceError,
        *,
        network_message: str,
        invalid_json_message: str,
        generic_message: str,
        unauthorized_message: str,
        forbidden_message: str,
    ) -> None:
        if exc.status_code == 401:
            raise SprintViewerServiceError(unauthorized_message) from exc
        if exc.status_code == 403:
            raise SprintViewerServiceError(forbidden_message) from exc
        if exc.message == "Invalid JSON response":
            raise SprintViewerServiceError(invalid_json_message) from exc
        if exc.status_code is not None:
            raise SprintViewerServiceError(
                f"{generic_message}: {exc.status_code} {(exc.response_snippet or '')[:200]}"
            ) from exc
        raise SprintViewerServiceError(f"{network_message}: {exc}") from exc
