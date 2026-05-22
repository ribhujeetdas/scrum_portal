# app/blueprints/automation/routes.py
from __future__ import annotations

from flask import current_app, render_template, jsonify, request
from flask_login import login_required, current_user

from ...extensions import db
from ...models import UserProject, UserBoard, UserBoardSprint
from ...services.crypto_service import CryptoService
from ...services.jira_service import JiraService, JiraServiceError
from ...services.rule_copier_service import RuleCopierService, RuleCopierServiceError
from ...services.sprint_viewer_service import SprintViewerService, SprintViewerServiceError
from . import automation_bp


def _crypto() -> CryptoService:
    return CryptoService(current_app.config["FERNET_KEY"])


def _jira_service() -> JiraService:
    return JiraService(current_app.config["JIRA_BASE_URL"])


def _rule_service() -> RuleCopierService:
    return RuleCopierService(current_app.config["JIRA_BASE_URL"])


def _sprint_service() -> SprintViewerService:
    return SprintViewerService(current_app.config["JIRA_BASE_URL"])


def _trace_api(msg: str, *args) -> None:
    if current_app.config.get("TRACE_SPRINT_VIEWER_API", False):
        current_app.logger.debug(msg, *args)


def _get_user_pat() -> str:
    if not current_user.jira_pat_enc:
        raise ValueError(
            "Enterprise Agile Jira PAT is not set. Please set it in Profile.")
    return _crypto().decrypt(current_user.jira_pat_enc)


def _validate_pat_belongs_to_user(pat: str) -> None:
    myself = _jira_service().fetch_myself(pat)
    api_email = (myself.get("emailAddress") or "").strip()
    active = bool(myself.get("active"))
    deleted = bool(myself.get("deleted"))
    if api_email.lower() != current_user.email.lower():
        raise ValueError(
            "Saved PAT belongs to a different user (email mismatch).")
    if not active or deleted:
        raise ValueError("Jira profile is not active or is deleted.")


def _ensure_project_id_for_user_project(project_key: str, board_id: int, pat: str) -> int:
    """
    Ensure jira numeric project_id is available in user_projects for given project_key.
    If missing, resolve via board issues API and persist.
    Always validates that the board belongs to the selected project_key.
    """
    proj = UserProject.query.filter_by(
        user_id=current_user.id, project_key=project_key).first()
    if not proj:
        raise ValueError(
            "Project not found for your account. Add it in Profile first.")

    resolved = _rule_service().resolve_project_from_board_issue(board_id, pat)
    resolved_project_id = int(resolved["project_id"])
    resolved_project_key = str(resolved["project_key"]).strip().upper()

    if resolved_project_key != project_key:
        raise ValueError(
            f"Selected board belongs to project {resolved_project_key}, but you selected project {project_key}."
        )

    if proj.project_id != resolved_project_id:
        proj.project_id = resolved_project_id
        db.session.commit()

    return resolved_project_id


def _board_belongs_to_user_and_project(user_id: int, project_key: str, board_id: int) -> bool:
    q = (
        UserBoard.query.join(
            UserProject, UserBoard.project_id == UserProject.id)
        .filter(
            UserProject.user_id == user_id,
            UserProject.project_key == project_key,
            UserBoard.board_id == board_id,
        )
        .first()
    )
    return q is not None


def _board_belongs_to_user(user_id: int, board_id: int) -> bool:
    """
    Used by /sprint-viewer/issues and /sprint-viewer/metrics where we have board_id+sprint_id.
    """
    q = (
        UserBoard.query.join(
            UserProject, UserBoard.project_id == UserProject.id)
        .filter(
            UserProject.user_id == user_id,
            UserBoard.board_id == board_id,
        )
        .first()
    )
    return q is not None


# ---------------------------
# Rule Copier (unchanged)
# ---------------------------
@automation_bp.route("/rule-copier", methods=["GET"])
@login_required
def rule_copier_page():
    projects = (
        UserProject.query.filter_by(
            user_id=current_user.id, admin_projects=True)
        .order_by(UserProject.project_key.asc())
        .all()
    )
    boards_by_project: dict[str, list[dict]] = {}
    for p in projects:
        boards = (
            UserBoard.query.join(
                UserProject, UserBoard.project_id == UserProject.id)
            .filter(UserProject.user_id == current_user.id, UserProject.id == p.id)
            .order_by(UserBoard.board_name.asc())
            .all()
        )
        boards_by_project[p.project_key] = [
            {
                "board_id": b.board_id,
                "board_name": b.board_name,
                "board_type": b.board_type,
                "board_url": b.board_url,
            }
            for b in boards
        ]

    return render_template(
        "automation/rule_copier.html",
        projects=[p.project_key for p in projects],
        boards_by_project=boards_by_project,
    )


@automation_bp.route("/rule-copier/fetch-rule", methods=["POST"])
@login_required
def fetch_rule():
    payload = request.get_json(silent=True) or {}
    project_key = str(payload.get("project_key") or "").strip().upper()
    board_id = payload.get("board_id")
    rule_id = payload.get("rule_id")

    try:
        board_id_int = int(board_id)
        rule_id_int = int(rule_id)
    except Exception:
        return jsonify({"ok": False, "error": "Board ID and Rule ID must be numeric."}), 400

    if not project_key:
        return jsonify({"ok": False, "error": "Project key is required."}), 400

    try:
        pat = _get_user_pat()
        _validate_pat_belongs_to_user(pat)
    except JiraServiceError as exc:
        return jsonify({"ok": False, "error": f"PAT validation failed: {exc}"}), 403
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403

    try:
        jira_project_id = _ensure_project_id_for_user_project(
            project_key, board_id_int, pat)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    try:
        rule_json = _rule_service().get_rule_detail(jira_project_id, rule_id_int, pat)
    except RuleCopierServiceError as exc:
        current_app.logger.warning("Fetch rule failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception as exc:
        current_app.logger.exception("Unexpected error in fetch_rule: %s", exc)
        return jsonify({"ok": False, "error": "Unexpected error occurred."}), 500

    rule_out = {
        "id": rule_json.get("id", rule_id_int),
        "name": rule_json.get("name", ""),
        "state": rule_json.get("state", ""),
    }

    return jsonify(
        {
            "ok": True,
            "project_key": project_key,
            "project_id": jira_project_id,
            "board_id": board_id_int,
            "rule": rule_out,
            "rule_json": rule_json,
        }
    )


@automation_bp.route("/rule-copier/copy-rule", methods=["POST"])
@login_required
def copy_rule():
    payload = request.get_json(silent=True) or {}
    target_project_key = str(payload.get(
        "target_project_key") or "").strip().upper()
    target_board_id = payload.get("target_board_id")
    rule_json = payload.get("rule_json")

    try:
        target_board_id_int = int(target_board_id)
    except Exception:
        return jsonify({"ok": False, "error": "Target board id must be numeric."}), 400

    if not target_project_key:
        return jsonify({"ok": False, "error": "Target project key is required."}), 400
    if not isinstance(rule_json, dict):
        return jsonify({"ok": False, "error": "rule_json is missing or invalid."}), 400

    try:
        pat = _get_user_pat()
        _validate_pat_belongs_to_user(pat)
    except JiraServiceError as exc:
        return jsonify({"ok": False, "error": f"PAT validation failed: {exc}"}), 403
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403

    try:
        target_jira_project_id = _ensure_project_id_for_user_project(
            target_project_key, target_board_id_int, pat)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if not current_user.jira_key:
        return jsonify({"ok": False, "error": "Your jira_key is missing in DB. Please contact admin."}), 400

    author_account_id = str(current_user.jira_key).strip()
    actor_account_id = current_app.config["JIRA_AUTOMATION_ACTOR_ACCOUNT_ID"]

    try:
        create_payload = _rule_service().transform_rule_for_create(
            rule_json=rule_json,
            target_project_id=target_jira_project_id,
            author_account_id=author_account_id,
            actor_account_id=actor_account_id,
        )
        try:
            created = _rule_service().create_rule(
                target_jira_project_id, create_payload, pat)
        except RuleCopierServiceError:
            created = _rule_service().create_rule(target_project_key, create_payload, pat)

        return jsonify(
            {
                "ok": True,
                "message": "Rule copied successfully.",
                "target_project_key": target_project_key,
                "target_project_id": target_jira_project_id,
                "target_board_id": target_board_id_int,
                "created": created,
            }
        )
    except RuleCopierServiceError as exc:
        current_app.logger.warning("Copy rule failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception("Unexpected error in copy_rule: %s", exc)
        return jsonify({"ok": False, "error": "Unexpected error occurred."}), 500


# ---------------------------
# Sprint Viewer
# ---------------------------
@automation_bp.route("/sprint-viewer", methods=["GET"])
@login_required
def sprint_viewer_page():
    projects = (
        UserProject.query.filter_by(
            user_id=current_user.id, admin_projects=True)
        .order_by(UserProject.project_key.asc())
        .all()
    )
    boards_by_project: dict[str, list[dict]] = {}
    for p in projects:
        boards = (
            UserBoard.query.join(
                UserProject, UserBoard.project_id == UserProject.id)
            .filter(UserProject.user_id == current_user.id, UserProject.id == p.id)
            .order_by(UserBoard.board_name.asc())
            .all()
        )
        boards_by_project[p.project_key] = [
            {
                "board_id": b.board_id,
                "board_name": b.board_name,
                "board_type": b.board_type,
                "board_url": b.board_url,
            }
            for b in boards
        ]

    return render_template(
        "automation/sprint_viewer.html",
        projects=[p.project_key for p in projects],
        boards_by_project=boards_by_project,
        jira_base_url=current_app.config["JIRA_BASE_URL"].rstrip("/"),
        trace_ui=bool(current_app.config.get("TRACE_SPRINT_VIEWER_UI", False)),
    )


@automation_bp.route("/sprint-viewer/sprints", methods=["POST"])
@login_required
def sprint_viewer_get_sprints():
    """
    Payload:
      { project_key, board_id, refresh: bool }
    """
    payload = request.get_json(silent=True) or {}
    project_key = str(payload.get("project_key") or "").strip().upper()
    board_id = payload.get("board_id")
    refresh = bool(payload.get("refresh", False))

    try:
        board_id_int = int(board_id)
    except Exception:
        return jsonify({"ok": False, "error": "Board ID must be numeric."}), 400

    if not project_key:
        return jsonify({"ok": False, "error": "Project key is required."}), 400

    if not _board_belongs_to_user_and_project(current_user.id, project_key, board_id_int):
        return jsonify({"ok": False, "error": "Selected board does not belong to selected project for this user."}), 403

    try:
        pat = _get_user_pat()
        _validate_pat_belongs_to_user(pat)
    except JiraServiceError as exc:
        return jsonify({"ok": False, "error": f"PAT validation failed: {exc}"}), 403
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403

    _trace_api("SprintViewer/sprints request user=%s project=%s board=%s refresh=%s",
               current_user.eid, project_key, board_id_int, refresh)

    existing = (
        UserBoardSprint.query.filter_by(
            user_id=current_user.id, board_id=board_id_int)
        .order_by(UserBoardSprint.sprint_id.desc())
        .all()
    )

    if refresh:
        try:
            UserBoardSprint.query.filter_by(
                user_id=current_user.id, board_id=board_id_int).delete()
            db.session.commit()
            existing = []
        except Exception:
            db.session.rollback()
            return jsonify({"ok": False, "error": "Failed to clear existing sprints from DB."}), 500

    if existing:
        return jsonify(
            {
                "ok": True,
                "source": "db",
                "sprints": [{"id": s.sprint_id, "name": s.sprint_name, "state": s.sprint_state} for s in existing],
            }
        )

    try:
        sprints = _sprint_service().fetch_closed_sprints_for_board(board_id_int, pat)
    except SprintViewerServiceError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    try:
        for s in sprints:
            db.session.add(
                UserBoardSprint(
                    user_id=current_user.id,
                    board_id=board_id_int,
                    sprint_id=int(s.get("id")),
                    sprint_name=(s.get("name") or "").strip(),
                    sprint_state=(s.get("state") or "").strip(),
                    sprint_url=(s.get("self") or "").strip(),
                    start_date=s.get("startDate"),
                    end_date=s.get("endDate"),
                    complete_date=s.get("completeDate"),
                    activated_date=s.get("activatedDate"),
                    origin_board_id=s.get("originBoardId"),
                    goal=s.get("goal"),
                    synced=bool(s.get("synced")) if s.get(
                        "synced") is not None else None,
                    auto_start_stop=bool(s.get("autoStartStop")) if s.get(
                        "autoStartStop") is not None else None,
                )
            )
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"ok": False, "error": "Failed to save sprints to DB."}), 500

    saved = (
        UserBoardSprint.query.filter_by(
            user_id=current_user.id, board_id=board_id_int)
        .order_by(UserBoardSprint.sprint_id.desc())
        .all()
    )

    _trace_api("SprintViewer/sprints saved user=%s board=%s count=%s",
               current_user.eid, board_id_int, len(saved))

    return jsonify(
        {
            "ok": True,
            "source": "jira",
            "sprints": [{"id": s.sprint_id, "name": s.sprint_name, "state": s.sprint_state} for s in saved],
        }
    )


@automation_bp.route("/sprint-viewer/issues", methods=["POST"])
@login_required
def sprint_viewer_fetch_issues():
    """
    Payload: { board_id, sprint_id }
    Behavior:
      - fetch ALL sprint issues (pagination), extract fields, group by assignee
      - compute total SP + helpful single-sprint stats (no extra API calls)
      - IMPORTANT: does NOT compute JQL metrics here (fast response)
    """
    payload = request.get_json(silent=True) or {}
    board_id = payload.get("board_id")
    sprint_id = payload.get("sprint_id")

    try:
        board_id_int = int(board_id)
        sprint_id_int = int(sprint_id)
    except Exception:
        return jsonify({"ok": False, "error": "Board ID and Sprint ID must be numeric."}), 400

    if not _board_belongs_to_user(current_user.id, board_id_int):
        return jsonify({"ok": False, "error": "Selected board does not belong to your saved projects."}), 403

    try:
        pat = _get_user_pat()
        _validate_pat_belongs_to_user(pat)
    except JiraServiceError as exc:
        return jsonify({"ok": False, "error": f"PAT validation failed: {exc}"}), 403
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403

    _trace_api("SprintViewer/issues request user=%s board=%s sprint=%s",
               current_user.eid, board_id_int, sprint_id_int)

    try:
        raw = _sprint_service().fetch_all_issues_for_sprint(sprint_id_int, pat)
        total = raw["total"]
        issues_raw = raw["issues"]

        extracted = [_sprint_service().extract_issue_fields(i)
                     for i in issues_raw]
        grouped = _sprint_service().group_issues_by_assignee(extracted)
        total_sp = _sprint_service().sum_story_points(extracted)

        stats = _sprint_service().compute_issue_quality_stats(extracted)

        _trace_api(
            "SprintViewer/issues done user=%s board=%s sprint=%s total=%s total_sp=%.2f unestimated=%s bugs=%s",
            current_user.eid, board_id_int, sprint_id_int, total, total_sp,
            stats.get("unestimated_count"), stats.get("bug_count")
        )

        return jsonify(
            {
                "ok": True,
                "total": int(total),
                "total_sp": round(float(total_sp), 2),
                "groups": grouped,
                "stats": stats,
            }
        )
    except SprintViewerServiceError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception(
            "Unexpected error in sprint_viewer_fetch_issues: %s", exc)
        return jsonify({"ok": False, "error": "Unexpected error occurred."}), 500


@automation_bp.route("/sprint-viewer/metrics", methods=["POST"])
@login_required
def sprint_viewer_fetch_metrics():
    """
    Payload: { board_id, sprint_id, total_sp, total_count }
    Behavior:
      - runs ScriptRunner JQL searches in parallel
      - returns SP + counts + scope_added issue keys (for UI star)
    """
    payload = request.get_json(silent=True) or {}
    board_id = payload.get("board_id")
    sprint_id = payload.get("sprint_id")
    total_sp = payload.get("total_sp")
    total_count = payload.get("total_count")

    try:
        board_id_int = int(board_id)
        sprint_id_int = int(sprint_id)
        total_sp_val = float(total_sp) if total_sp is not None else 0.0
        total_count_val = int(total_count) if total_count is not None else 0
    except Exception:
        return jsonify({"ok": False, "error": "Board ID and Sprint ID must be numeric; total_sp and total_count must be numeric."}), 400

    if not _board_belongs_to_user(current_user.id, board_id_int):
        return jsonify({"ok": False, "error": "Selected board does not belong to your saved projects."}), 403

    try:
        pat = _get_user_pat()
        _validate_pat_belongs_to_user(pat)
    except JiraServiceError as exc:
        return jsonify({"ok": False, "error": f"PAT validation failed: {exc}"}), 403
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403

    _trace_api(
        "SprintViewer/metrics request user=%s board=%s sprint=%s total_sp=%.2f total_count=%s",
        current_user.eid, board_id_int, sprint_id_int, total_sp_val, total_count_val
    )

    try:
        metrics = _sprint_service().compute_sprint_metrics_parallel(
            board_id=board_id_int,
            sprint_id=sprint_id_int,
            pat=pat,
            total_sp=total_sp_val,
            total_count=total_count_val,
        )

        _trace_api(
            "SprintViewer/metrics done user=%s board=%s sprint=%s keys=%s",
            current_user.eid, board_id_int, sprint_id_int, len(
                metrics.get("scope_added_keys") or [])
        )

        return jsonify({"ok": True, "metrics": metrics})
    except SprintViewerServiceError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        current_app.logger.exception(
            "Unexpected error in sprint_viewer_fetch_metrics: %s", exc)
        return jsonify({"ok": False, "error": "Unexpected error occurred."}), 500
