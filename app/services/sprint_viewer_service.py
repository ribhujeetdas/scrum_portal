# app/services/sprint_viewer_service.py
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import re
from typing import Optional, Set, Dict, Any, List

from flask import current_app, has_app_context

from app.core.http_client import ExternalHttpClient, ExternalServiceError


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
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds
        self.metrics_max_workers = max(1, min(int(metrics_max_workers or 5), 16))
        if not self.base_url:
            raise ValueError("JIRA_BASE_URL is missing.")
        self._client = http_client or self._new_client()

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
    def _comment_slim(comment: dict) -> dict:
        return {
            "author_eid": SprintViewerService._comment_author_eid(comment),
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
    def _reconstruct_at_sprint_end(issue: dict, values: dict, sprint_complete_date: Optional[str]) -> tuple[dict, bool]:
        cutoff = SprintViewerService._parse_jira_datetime(sprint_complete_date)
        if cutoff is None:
            return values, False

        histories = ((issue.get("changelog") or {}).get("histories") or [])
        if not histories:
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
                    reconstructed["status"] = item.get("fromString") or reconstructed["status"]
                elif field == "assignee":
                    reconstructed["assignee_eid"] = item.get("from") or item.get("fromString") or reconstructed["assignee_eid"]
                    reconstructed["assignee_name"] = item.get("fromString") or reconstructed["assignee_name"]
                elif field in {"story points", "customfield_10106"}:
                    sp = SprintViewerService._safe_story_points(item.get("fromString"))
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
        all_sprints: list[dict] = []
        start_at = 0
        max_results = 50

        self._trace("Sprints start board_id=%s maxResults=%s",
                    board_id, max_results)

        while True:
            params = {"startAt": start_at,
                      "maxResults": max_results, "state": "closed"}

            try:
                data = self._client.get_json(
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

            values = data.get("values") or []
            page_count = len(values)

            for s in values:
                if (s.get("state") or "").lower() != "closed":
                    continue
                year = self._year_from_start_date(s.get("startDate"))
                if year is None or year not in allowed_years:
                    continue
                all_sprints.append(s)

            is_last = data.get("isLast")
            self._trace(
                "Sprints page board_id=%s startAt=%s got=%s isLast=%s total_collected=%s",
                board_id, start_at, page_count, is_last, len(all_sprints)
            )

            if is_last is True:
                self._trace("Sprints stop reason=isLast")
                break
            if page_count == 0:
                self._trace("Sprints stop reason=page_count=0")
                break
            if page_count < max_results:
                self._trace("Sprints stop reason=page_count<maxResults")
                break

            start_at += page_count

        self._trace("Sprints done board_id=%s final_count=%s",
                    board_id, len(all_sprints))
        return all_sprints

    # ---------------------------
    # Sprint issues (pagination)
    # ---------------------------
    def fetch_all_issues_for_sprint(self, sprint_id: int, pat: str) -> dict:
        start_at = 0
        max_results = 50
        all_issues: list[dict] = []
        total: Optional[int] = None

        fields = [
            "summary",
            "customfield_10106",  # story points
            "issuetype",
            "status",
            "customfield_11700",  # app
            "epic",
            "comment",
            "assignee",
            "parent",
        ]

        self._trace("SprintIssues start sprint_id=%s maxResults=%s",
                    sprint_id, max_results)

        while True:
            params = {"startAt": start_at, "maxResults": max_results,
                      "fields": ",".join(fields), "expand": "changelog"}

            try:
                data = self._client.get_json(
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

            if total is None:
                t = data.get("total")
                total = int(t) if isinstance(t, int) else None

            issues = data.get("issues") or []
            self._hydrate_incomplete_comments(issues, pat)
            all_issues.extend(issues)

            page_count = len(issues)
            is_last = data.get("isLast")

            self._trace(
                "SprintIssues page sprint_id=%s startAt=%s got=%s isLast=%s total=%s collected=%s",
                sprint_id, start_at, page_count, is_last, total, len(
                    all_issues)
            )

            if is_last is True:
                self._trace("SprintIssues stop reason=isLast")
                break
            if page_count == 0:
                self._trace("SprintIssues stop reason=page_count=0")
                break
            if page_count < max_results:
                self._trace("SprintIssues stop reason=page_count<maxResults")
                break
            if total is not None:
                try:
                    if (start_at + page_count) >= int(total):
                        self._trace("SprintIssues stop reason=reached_total")
                        break
                except Exception:
                    pass

            start_at += page_count

        final_total = int(total) if total is not None else len(all_issues)
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
    def extract_issue_fields(issue: dict, sprint_complete_date: Optional[str] = None) -> dict:
        fields = issue.get("fields") or {}
        assignee = fields.get("assignee") or {}
        assignee_eid = assignee.get("name") or "UNASSIGNED"
        assignee_name = assignee.get("displayName") or "Unassigned"

        issuetype = fields.get("issuetype") or {}
        status = fields.get("status") or {}
        is_subtask = bool(issuetype.get("subtask"))

        app_obj = fields.get("customfield_11700") or {}
        app_name = app_obj.get("value") or ""

        epic_obj = fields.get("epic") or {}
        epic_key = epic_obj.get("key") or (
            fields.get("customfield_10100") or "")
        epic_name = epic_obj.get("name") or ""

        comment_obj = fields.get("comment") or {}
        comment_total = comment_obj.get("total") or 0
        comments = [
            SprintViewerService._comment_slim(comment)
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
            "comment_total": int(comment_total or 0),
            "comments": comments,
            "relevant_comment_count": 0,
            "is_carryover": SprintViewerService._issue_has_multiple_sprints(issue),
            "assignee_eid": assignee_eid,
            "assignee_name": assignee_name,
        }
        values, historical_fallback = SprintViewerService._reconstruct_at_sprint_end(
            issue, values, sprint_complete_date
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
        team_eids = {
            str(issue.get("assignee_eid") or "").strip()
            for issue in extracted_issues
            if issue.get("assignee_eid") and issue.get("assignee_eid") != "UNASSIGNED"
        }
        cutoff = SprintViewerService._parse_jira_datetime(sprint_complete_date)

        for issue in extracted_issues:
            assignee_eid = str(issue.get("assignee_eid") or "").strip()
            allowed_authors = set(team_eids)
            if assignee_eid and assignee_eid != "UNASSIGNED":
                allowed_authors.add(assignee_eid)

            count = 0
            for comment in issue.get("comments") or []:
                author_eid = str(comment.get("author_eid") or "").strip()
                if author_eid not in allowed_authors:
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
            if eid not in groups:
                groups[eid] = {
                    "assignee_eid": eid,
                    "assignee_name": it["assignee_name"],
                    "issues": [],
                    "issue_count": 0,
                    "sp_sum": 0.0,
                }

            groups[eid]["issues"].append(it)
            groups[eid]["issue_count"] += 1
            groups[eid]["sp_sum"] += self._safe_float(it.get("story_points"))
            groups[eid]["relevant_comment_count"] = (
                groups[eid].get("relevant_comment_count", 0)
                + int(it.get("relevant_comment_count") or 0)
            )

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
            "zero_comment_count": zero_comment_count,
            "zero_comment_pct": round(pct(zero_comment_count, total_count), 1),
            "relevant_comment_count": relevant_comment_count,
            "zero_relevant_comment_count": zero_relevant_comment_count,
            "zero_relevant_comment_pct": round(pct(zero_relevant_comment_count, total_count), 1),
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
            by_assignee.setdefault(
                assignee,
                {"assignee_eid": assignee, "assignee_name": assignee_name, "types": {}},
            )
            by_assignee[assignee]["types"].setdefault(issue_type, blank_bucket())
            by_assignee[assignee]["types"][issue_type]["count"] += 1
            by_assignee[assignee]["types"][issue_type]["pts"] += pts

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
        start_at = 0
        max_results = 200

        total_sp = 0.0
        total_count = 0
        keys: Set[str] = set()

        jql_short = jql.replace("\n", " ").strip()
        if len(jql_short) > 180:
            jql_short = jql_short[:180] + "..."

        self._trace_jql("JQLAgg start startAt=%s maxResults=%s jql=%s",
                        start_at, max_results, jql_short)

        while True:
            params = {
                "jql": jql,
                "startAt": start_at,
                "maxResults": max_results,
                "fields": "customfield_10106",
            }

            try:
                data = client.get_json(
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

            issues = data.get("issues") or []
            page_count = len(issues)
            total_count += page_count

            for issue in issues:
                if capture_keys:
                    k = issue.get("key")
                    if k:
                        keys.add(str(k))

                f = issue.get("fields") or {}
                sp = f.get("customfield_10106")
                if sp is None:
                    continue
                try:
                    total_sp += float(sp)
                except Exception:
                    continue

            is_last = data.get("isLast")
            self._trace_jql(
                "JQLAgg page startAt=%s got=%s isLast=%s count_so_far=%s sp_so_far=%.2f jql=%s",
                start_at, page_count, is_last, total_count, total_sp, jql_short
            )

            if is_last is True:
                self._trace_jql("JQLAgg stop reason=isLast jql=%s", jql_short)
                break
            if page_count == 0:
                self._trace_jql(
                    "JQLAgg stop reason=page_count=0 jql=%s", jql_short)
                break
            if page_count < max_results:
                self._trace_jql(
                    "JQLAgg stop reason=page_count<maxResults jql=%s", jql_short)
                break

            start_at += page_count

        out = {"sp": float(total_sp), "count": int(total_count)}
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
        original = results.get("original_commitment", {})
        completed_original = results.get("completed_original", {})
        total_completed = results.get("total_completed", {})
        added = results.get("added_scope", {})
        removed = results.get("removed_scope", {})

        original_sp = float(original.get("sp", 0.0))
        original_count = int(original.get("count", 0))
        completed_original_sp = float(completed_original.get("sp", 0.0))
        completed_original_count = int(completed_original.get("count", 0))
        total_completed_sp = float(total_completed.get("sp", 0.0))
        total_completed_count = int(total_completed.get("count", 0))
        added_sp = float(added.get("sp", 0.0))
        added_count = int(added.get("count", 0))
        removed_sp = float(removed.get("sp", 0.0))
        removed_count = int(removed.get("count", 0))

        completed_added_sp = max(0.0, total_completed_sp - completed_original_sp)
        completed_added_count = max(0, total_completed_count - completed_original_count)
        carryover_sp = max(0.0, original_sp - completed_original_sp - removed_sp)
        carryover_count = max(0, original_count - completed_original_count - removed_count)
        scope_net_sp = added_sp - removed_sp
        scope_net_count = added_count - removed_count

        def pct(n: float, d: float) -> float:
            return (n / d) * 100.0 if d and d > 0 else 0.0

        out = {
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
            "scope_net_sp": round(scope_net_sp, 2),
            "scope_net_count": scope_net_count,
            "commitment_predictability_pct": round(pct(completed_original_sp, original_sp), 1),
            "total_delivery_vs_commitment_pct": round(pct(total_completed_sp, original_sp), 1),
            "added_scope_pct": round(pct(added_sp, original_sp), 1),
            "removed_scope_pct": round(pct(removed_sp, original_sp), 1),
            "scope_change_pct": round(pct(added_sp + removed_sp, original_sp), 1),
            "scope_added_keys": added.get("keys") or [],
        }

        # Backward-compatible aliases for existing callers/UI during migration.
        out.update(
            {
                "committed_sp": out["original_commitment_sp"],
                "committed_count": out["original_commitment_count"],
                "delivered_sp": out["total_completed_sp"],
                "delivered_count": out["total_completed_count"],
                "spillover_sp": out["carryover_sp"],
                "spillover_count": out["carryover_count"],
                "scope_added_sp": out["added_scope_sp"],
                "scope_added_count": out["added_scope_count"],
                "descope_sp": out["removed_scope_sp"],
                "descope_count": out["removed_scope_count"],
                "predictability_pct": out["commitment_predictability_pct"],
                "spill_pct": round(pct(carryover_sp, original_sp), 1),
                "scope_pct": out["added_scope_pct"],
                "spill_red": pct(carryover_sp, original_sp) > 20.0,
                "scope_red": out["added_scope_pct"] > 20.0,
            }
        )
        return out

    def compute_sprint_metrics_parallel(self, board_id: int, sprint_id: int, pat: str, total_sp: float, total_count: int) -> dict:
        # ScriptRunner JQLs already used in our app
        completed_jql = f"issueFunction in completeInSprint({board_id}, {sprint_id}) AND issuetype IN standardIssueTypes()"
        completed_original_jql = f"issueFunction in completeInSprint({board_id}, {sprint_id}) AND issueFunction NOT IN addedAfterSprintStart({board_id},{sprint_id}) AND issuetype IN standardIssueTypes()"
        added_scope_jql = f"issueFunction in addedAfterSprintStart({board_id},{sprint_id}) AND issuetype IN standardIssueTypes()"
        removed_scope_jql = f"issueFunction in removedAfterSprintStart({board_id},{sprint_id}) AND issuetype IN standardIssueTypes()"
        original_commitment_jql = (
            f"(issueFunction in completeInSprint({board_id}, {sprint_id}) "
            f"OR issueFunction in incompleteInSprint({board_id},{sprint_id}) "
            f"OR issueFunction in removedAfterSprintStart({board_id},{sprint_id})) "
            f"AND issueFunction NOT IN addedAfterSprintStart({board_id},{sprint_id}) "
            "AND issuetype IN standardIssueTypes()"
        )

        jobs = {
            "original_commitment": {"jql": original_commitment_jql, "capture_keys": False},
            "completed_original": {"jql": completed_original_jql, "capture_keys": False},
            "total_completed": {"jql": completed_jql, "capture_keys": False},
            "added_scope": {"jql": added_scope_jql, "capture_keys": True},
            "removed_scope": {"jql": removed_scope_jql, "capture_keys": False},
        }

        self._trace("Metrics start board_id=%s sprint_id=%s total_sp=%.2f total_count=%s",
                    board_id, sprint_id, total_sp, total_count)

        results: Dict[str, dict] = {k: {"sp": 0.0, "count": 0} for k in jobs.keys()}

        def run_one(name: str, spec: dict) -> tuple[str, dict]:
            agg = self._aggregate_by_jql_with_client(
                client=self._new_client(),
                jql=spec["jql"],
                pat=pat,
                capture_keys=bool(spec.get("capture_keys", False)),
            )
            return name, agg

        with ThreadPoolExecutor(max_workers=self.metrics_max_workers) as ex:
            futures = [ex.submit(run_one, name, spec)
                       for name, spec in jobs.items()]
            for f in as_completed(futures):
                name, agg = f.result()
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
