from __future__ import annotations

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

from ....core.api import json_error, json_ok, safe_error_message
from ....core.dependencies import crypto_service, jira_service, rule_copier_service
from ....core.error_logging import log_handled_exception
from ....core.jira_pat_validation import validate_jira_pat_for_current_user
from ....extensions import db
from ....models import UserBoard, UserProject
from ....services.jira_service import JiraServiceError
from ....services.rule_copier_service import RuleCopierService, RuleCopierServiceError


def _rule_service() -> RuleCopierService:
    return rule_copier_service()


def _get_user_pat() -> str:
    if not current_user.jira_pat_enc:
        raise ValueError(
            "Enterprise Agile Jira PAT is not set. Please set it in Profile.")
    return crypto_service().decrypt(current_user.jira_pat_enc)


def _validate_pat_belongs_to_user(pat: str) -> None:
    validate_jira_pat_for_current_user(pat, jira_service().fetch_myself)


def _ensure_project_id_for_user_project(project_key: str, board_id: int, pat: str) -> int:
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


def _create_rule_with_identifier_fallback(
    service: RuleCopierService,
    target_project_id: int,
    target_project_key: str,
    create_payload: dict,
    pat: str,
) -> dict:
    first_exc: RuleCopierServiceError | None = None
    for project_identifier in (target_project_id, target_project_key):
        try:
            return service.create_rule(project_identifier, create_payload, pat)
        except RuleCopierServiceError as exc:
            first_exc = exc
            log_handled_exception(
                "Rule Copier create-rule attempt failed",
                exc,
                event="automation.rule_copier.create_attempt_failed",
                feature="rule_copier",
                operation="copy_rule",
                context={
                    "project_identifier": project_identifier,
                    "actor_account_id": create_payload.get("actorAccountId"),
                },
            )
    if first_exc:
        raise first_exc
    raise RuleCopierServiceError("Create rule failed before making an API attempt.")


def rule_copier_page():
    projects = (
        UserProject.query.filter_by(
            user_id=current_user.id, admin_projects=True)
        .order_by(UserProject.project_key.asc())
        .all()
    )
    if not projects:
        flash(
            "No project key found. Redirecting you to Settings to add Projects & Boards.",
            "warning",
        )
        return redirect(url_for("aliases.settings_projects_boards"))

    boards_by_project: dict[str, list[dict]] = {}
    for project in projects:
        boards = (
            UserBoard.query.join(
                UserProject, UserBoard.project_id == UserProject.id)
            .filter(UserProject.user_id == current_user.id, UserProject.id == project.id)
            .order_by(UserBoard.board_name.asc())
            .all()
        )
        boards_by_project[project.project_key] = [
            {
                "board_id": board.board_id,
                "board_name": board.board_name,
                "board_type": board.board_type,
                "board_url": board.board_url,
            }
            for board in boards
        ]

    return render_template(
        "automation/rule_copier.html",
        projects=[project.project_key for project in projects],
        boards_by_project=boards_by_project,
    )


def fetch_rule():
    payload = request.get_json(silent=True) or {}
    project_key = str(payload.get("project_key") or "").strip().upper()
    board_id = payload.get("board_id")
    rule_id = payload.get("rule_id")

    try:
        board_id_int = int(board_id)
        rule_id_int = int(rule_id)
    except Exception:
        return json_error("Board ID and Rule ID must be numeric.", status_code=400)

    if not project_key:
        return json_error("Project key is required.", status_code=400)

    try:
        pat = _get_user_pat()
        _validate_pat_belongs_to_user(pat)
    except JiraServiceError as exc:
        log_handled_exception(
            "Rule Copier PAT validation failed",
            exc,
            event="automation.rule_copier.pat_validation_failed",
            feature="rule_copier",
            operation="fetch_rule",
        )
        return json_error(safe_error_message("validate Jira access"), status_code=403)
    except Exception as exc:
        return json_error(str(exc), status_code=403)

    try:
        jira_project_id = _ensure_project_id_for_user_project(
            project_key, board_id_int, pat)
    except RuleCopierServiceError as exc:
        log_handled_exception(
            "Rule Copier project resolution failed",
            exc,
            event="automation.rule_copier.project_resolution_failed",
            feature="rule_copier",
            operation="fetch_rule",
            context={"project_key": project_key, "board_id": board_id_int},
        )
        return json_error(safe_error_message("validate selected project and board"), status_code=400)
    except ValueError as exc:
        return json_error(str(exc), status_code=400)

    try:
        rule_json = _rule_service().get_rule_detail(jira_project_id, rule_id_int, pat)
    except RuleCopierServiceError as exc:
        log_handled_exception(
            "Rule Copier failed to fetch rule",
            exc,
            event="automation.rule_copier.fetch_failed",
            feature="rule_copier",
            operation="fetch_rule",
            context={
                "project_key": project_key,
                "project_id": jira_project_id,
                "board_id": board_id_int,
                "rule_id": rule_id_int,
            },
        )
        return json_error(safe_error_message("fetch the automation rule"), status_code=404)
    except Exception as exc:
        current_app.logger.exception("Unexpected error in fetch_rule: %s", exc)
        return json_error("Unexpected error occurred.", status_code=500)

    rule_out = {
        "id": rule_json.get("id", rule_id_int),
        "name": rule_json.get("name", ""),
        "state": rule_json.get("state", ""),
    }

    return json_ok(
        project_key=project_key,
        project_id=jira_project_id,
        board_id=board_id_int,
        rule=rule_out,
        rule_json=rule_json,
    )


def copy_rule():
    payload = request.get_json(silent=True) or {}
    target_project_key = str(payload.get(
        "target_project_key") or "").strip().upper()
    target_board_id = payload.get("target_board_id")
    rule_json = payload.get("rule_json")

    try:
        target_board_id_int = int(target_board_id)
    except Exception:
        return json_error("Target board id must be numeric.", status_code=400)

    if not target_project_key:
        return json_error("Target project key is required.", status_code=400)
    if not isinstance(rule_json, dict):
        return json_error("rule_json is missing or invalid.", status_code=400)

    try:
        pat = _get_user_pat()
        _validate_pat_belongs_to_user(pat)
    except JiraServiceError as exc:
        log_handled_exception(
            "Rule Copier PAT validation failed",
            exc,
            event="automation.rule_copier.pat_validation_failed",
            feature="rule_copier",
            operation="copy_rule",
        )
        return json_error(safe_error_message("validate Jira access"), status_code=403)
    except Exception as exc:
        return json_error(str(exc), status_code=403)

    try:
        target_jira_project_id = _ensure_project_id_for_user_project(
            target_project_key, target_board_id_int, pat)
    except RuleCopierServiceError as exc:
        log_handled_exception(
            "Rule Copier project resolution failed",
            exc,
            event="automation.rule_copier.project_resolution_failed",
            feature="rule_copier",
            operation="copy_rule",
            context={"target_project_key": target_project_key, "target_board_id": target_board_id_int},
        )
        return json_error(safe_error_message("validate selected project and board"), status_code=400)
    except ValueError as exc:
        return json_error(str(exc), status_code=400)

    if not current_user.jira_key:
        return json_error("Your jira_key is missing in DB. Please contact admin.", status_code=400)

    author_account_id = str(current_user.jira_key).strip()
    configured_actor_account_id = str(
        current_app.config["JIRA_AUTOMATION_ACTOR_ACCOUNT_ID"]
    ).strip()

    try:
        service = _rule_service()
        create_payload = service.transform_rule_for_create(
            rule_json=rule_json,
            target_project_id=target_jira_project_id,
            author_account_id=author_account_id,
            actor_account_id=configured_actor_account_id,
        )
        try:
            created = _create_rule_with_identifier_fallback(
                service,
                target_jira_project_id,
                target_project_key,
                create_payload,
                pat,
            )
            actor_used = configured_actor_account_id
        except RuleCopierServiceError as configured_actor_exc:
            if configured_actor_account_id == author_account_id:
                raise

            log_handled_exception(
                "Configured automation actor failed; retrying with requesting user's Jira actor",
                configured_actor_exc,
                event="automation.rule_copier.actor_fallback",
                feature="rule_copier",
                operation="copy_rule",
                context={
                    "eid": current_user.eid,
                    "target_project_key": target_project_key,
                    "configured_actor_account_id": configured_actor_account_id,
                    "user_actor_account_id": author_account_id,
                },
            )
            user_actor_payload = service.transform_rule_for_create(
                rule_json=rule_json,
                target_project_id=target_jira_project_id,
                author_account_id=author_account_id,
                actor_account_id=author_account_id,
            )
            created = _create_rule_with_identifier_fallback(
                service,
                target_jira_project_id,
                target_project_key,
                user_actor_payload,
                pat,
            )
            actor_used = author_account_id

        return json_ok(
            message="Rule copied successfully.",
            target_project_key=target_project_key,
            target_project_id=target_jira_project_id,
            target_board_id=target_board_id_int,
            actor_used=actor_used,
            created=created,
        )
    except RuleCopierServiceError as exc:
        log_handled_exception(
            "Rule Copier failed to copy rule",
            exc,
            event="automation.rule_copier.copy_failed",
            feature="rule_copier",
            operation="copy_rule",
            context={
                "target_project_key": target_project_key,
                "target_board_id": target_board_id_int,
            },
        )
        return json_error(safe_error_message("copy the automation rule"), status_code=400)
    except Exception as exc:
        current_app.logger.exception("Unexpected error in copy_rule: %s", exc)
        return json_error("Unexpected error occurred.", status_code=500)
