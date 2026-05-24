# app/services/sprint_viewer_service.py
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
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
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds
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
        ]

        self._trace("SprintIssues start sprint_id=%s maxResults=%s",
                    sprint_id, max_results)

        while True:
            params = {"startAt": start_at, "maxResults": max_results,
                      "fields": ",".join(fields)}

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

    # ---------------------------
    # Field extraction / grouping
    # ---------------------------
    @staticmethod
    def extract_issue_fields(issue: dict) -> dict:
        fields = issue.get("fields") or {}
        assignee = fields.get("assignee") or {}
        assignee_eid = assignee.get("name") or "UNASSIGNED"
        assignee_name = assignee.get("displayName") or "Unassigned"

        issuetype = fields.get("issuetype") or {}
        status = fields.get("status") or {}

        app_obj = fields.get("customfield_11700") or {}
        app_name = app_obj.get("value") or ""

        epic_obj = fields.get("epic") or {}
        epic_key = epic_obj.get("key") or (
            fields.get("customfield_10100") or "")
        epic_name = epic_obj.get("name") or ""

        comment_obj = fields.get("comment") or {}
        comment_total = comment_obj.get("total") or 0

        return {
            "issue_id": issue.get("id"),
            "issue_key": issue.get("key"),
            "summary": fields.get("summary") or "",
            "story_points": fields.get("customfield_10106"),
            "issue_type": issuetype.get("name") or "",
            "status": status.get("name") or "",
            "app_name": app_name,
            "feature_key": epic_key,
            "feature_name": epic_name,
            "comment_total": int(comment_total or 0),
            "assignee_eid": assignee_eid,
            "assignee_name": assignee_name,
        }

    @staticmethod
    def _safe_float(v: Any) -> float:
        if v is None:
            return 0.0
        try:
            return float(v)
        except Exception:
            return 0.0

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
    def compute_sprint_metrics_parallel(self, board_id: int, sprint_id: int, pat: str, total_sp: float, total_count: int) -> dict:
        # ScriptRunner JQLs already used in our app
        delivered_jql = f"issueFunction in completeInSprint({board_id}, {sprint_id}) AND issuetype IN standardIssueTypes()"
        spillover_jql = f"issueFunction in incompleteInSprint({board_id},{sprint_id}) AND issuetype IN standardIssueTypes()"
        scope_added_jql = f"issueFunction in addedAfterSprintStart({board_id},{sprint_id}) AND issuetype IN standardIssueTypes()"
        descope_jql = f"issueFunction in removedAfterSprintStart({board_id},{sprint_id}) AND issuetype IN standardIssueTypes()"
        committed_jql = f"Sprint = {sprint_id} AND issueFunction NOT IN addedAfterSprintStart({board_id},{sprint_id}) AND issuetype IN standardIssueTypes()"

        jobs = {
            "delivered": {"jql": delivered_jql, "capture_keys": False},
            "spillover": {"jql": spillover_jql, "capture_keys": False},
            # needed for UI star
            "scope_added": {"jql": scope_added_jql, "capture_keys": True},
            "descope": {"jql": descope_jql, "capture_keys": False},
            "committed": {"jql": committed_jql, "capture_keys": False},
        }

        self._trace("Metrics start board_id=%s sprint_id=%s total_sp=%.2f total_count=%s",
                    board_id, sprint_id, total_sp, total_count)

        results: Dict[str, dict] = {
            k: {"sp": 0.0, "count": 0} for k in jobs.keys()}
        scope_added_keys: list[str] = []

        def run_one(name: str, spec: dict) -> tuple[str, dict]:
            agg = self._aggregate_by_jql_with_client(
                client=self._new_client(),
                jql=spec["jql"],
                pat=pat,
                capture_keys=bool(spec.get("capture_keys", False)),
            )
            return name, agg

        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(run_one, name, spec)
                       for name, spec in jobs.items()]
            for f in as_completed(futures):
                name, agg = f.result()
                results[name] = agg
                self._trace("Metrics partial %s sp=%.2f count=%s", name, float(
                    agg.get("sp", 0.0)), int(agg.get("count", 0)))
                if name == "scope_added" and isinstance(agg.get("keys"), list):
                    scope_added_keys = agg["keys"]

        delivered_sp = float(results["delivered"]["sp"])
        spillover_sp = float(results["spillover"]["sp"])
        scope_added_sp = float(results["scope_added"]["sp"])
        descope_sp = float(results["descope"]["sp"])
        committed_sp = float(results["committed"]["sp"])

        delivered_count = int(results["delivered"]["count"])
        spillover_count = int(results["spillover"]["count"])
        scope_added_count = int(results["scope_added"]["count"])
        descope_count = int(results["descope"]["count"])
        committed_count = int(results["committed"]["count"])

        def pct(n: float, d: float) -> float:
            if d and d > 0:
                return (n / d) * 100.0
            return 0.0

        # Existing metrics
        predictability_pct = pct(delivered_sp, committed_sp)
        spill_pct = pct(spillover_sp, total_sp)
        scope_pct = pct(scope_added_sp, committed_sp)

        # NEW single-sprint metrics (closed sprint analysis)
        completion_sp_pct = pct(delivered_sp, total_sp)
        completion_count_pct = pct(delivered_count, total_count)

        scope_churn_sp_pct = pct(scope_added_sp + descope_sp, committed_sp)
        scope_churn_count_pct = pct(
            scope_added_count + descope_count, committed_count)

        unplanned_sp_pct = pct(scope_added_sp, total_sp)
        unplanned_count_pct = pct(scope_added_count, total_count)

        out = {
            # SP + count pairs
            "delivered_sp": round(delivered_sp, 2),
            "delivered_count": delivered_count,
            "spillover_sp": round(spillover_sp, 2),
            "spillover_count": spillover_count,
            "scope_added_sp": round(scope_added_sp, 2),
            "scope_added_count": scope_added_count,
            "descope_sp": round(descope_sp, 2),
            "descope_count": descope_count,
            "committed_sp": round(committed_sp, 2),
            "committed_count": committed_count,

            # existing percentages
            "predictability_pct": round(predictability_pct, 1),
            "spill_pct": round(spill_pct, 1),
            "scope_pct": round(scope_pct, 1),
            "spill_red": spill_pct > 20.0,
            "scope_red": scope_pct > 20.0,

            # NEW single-sprint perspectives
            "completion_sp_pct": round(completion_sp_pct, 1),
            "completion_count_pct": round(completion_count_pct, 1),
            "scope_churn_sp_pct": round(scope_churn_sp_pct, 1),
            "scope_churn_count_pct": round(scope_churn_count_pct, 1),
            "unplanned_sp_pct": round(unplanned_sp_pct, 1),
            "unplanned_count_pct": round(unplanned_count_pct, 1),

            # For UI: star scope-added issues
            "scope_added_keys": scope_added_keys,
        }

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
