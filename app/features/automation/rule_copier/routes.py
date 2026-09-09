from __future__ import annotations

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
import hashlib
import json

from ....core.api import json_error, json_ok, safe_error_message
from ....core.dependencies import crypto_service, jira_service, rule_copier_service
from ....core.error_logging import log_handled_exception
from ....core.jira_pat_validation import validate_jira_pat_for_current_user
from ....extensions import db
from ....models import ExternalOperation, UserBoard, UserProject
from ....services.jira_service import JiraServiceError
from ....services.rule_copier_service import RuleCopierService, RuleCopierServiceError
from ..sprint_viewer.schemas import InputValidationError, positive_jira_id, require_json_object


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
    try:
        return service.create_rule(target_project_id, create_payload, pat)
    except RuleCopierServiceError as exc:
        if not exc.definitive or exc.fallback_kind != "project_identifier":
            raise
        return service.create_rule(target_project_key, create_payload, pat)


def rule_copier_page():
    projects = (
        UserProject.query.options(selectinload(UserProject.boards)).filter_by(
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
        boards = sorted(project.boards, key=lambda board: board.board_name.casefold())
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
    try:
        payload = require_json_object(request.get_json(silent=True))
        board_id_int = positive_jira_id(payload.get("board_id"), "Board ID")
        rule_id_int = positive_jira_id(payload.get("rule_id"), "Rule ID")
    except InputValidationError as exc:
        return json_error(str(exc), status_code=400, code="INVALID_INPUT")
    project_key = str(payload.get("project_key") or "").strip().upper()

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
    try:
        payload = require_json_object(request.get_json(silent=True))
        target_board_id_int = positive_jira_id(payload.get("target_board_id"), "Target board ID")
    except InputValidationError as exc:
        return json_error(str(exc), status_code=400, code="INVALID_INPUT")
    target_project_key = str(payload.get(
        "target_project_key") or "").strip().upper()
    rule_json = payload.get("rule_json")

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
    idempotency_key = str(
        request.headers.get("Idempotency-Key") or payload.get("client_action_id") or ""
    ).strip()
    if not idempotency_key or len(idempotency_key) > 128:
        return json_error(
            "Idempotency-Key is required for rule creation.",
            status_code=400,
            code="IDEMPOTENCY_KEY_REQUIRED",
        )

    try:
        service = _rule_service()
        create_payload = service.transform_rule_for_create(
            rule_json=rule_json,
            target_project_id=target_jira_project_id,
            author_account_id=author_account_id,
            actor_account_id=configured_actor_account_id,
            idempotency_key=idempotency_key,
        )
        fingerprint_payload = {
            "user_id": current_user.id,
            "project_id": target_jira_project_id,
            "board_id": target_board_id_int,
            "payload": create_payload,
        }
        fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        operation = ExternalOperation.query.filter_by(
            user_id=current_user.id, operation="rule_create", idempotency_key=idempotency_key
        ).first()
        if operation:
            if operation.request_fingerprint != fingerprint:
                return json_error("Idempotency key is already bound to another request.", status_code=409, code="IDEMPOTENCY_CONFLICT")
            if operation.state == "succeeded":
                return json_ok(message="Rule copy already completed.", operation_id=operation.id, created={"id": operation.external_result_id})
            return json_error("The previous rule creation outcome requires review.", status_code=409, code="EXTERNAL_OUTCOME_UNKNOWN", details={"operation_id": operation.id})
        outstanding = ExternalOperation.query.filter(
            ExternalOperation.user_id == current_user.id,
            ExternalOperation.operation == "rule_create",
            ExternalOperation.request_fingerprint == fingerprint,
            ExternalOperation.state.in_(("sending", "unknown")),
        ).first()
        if outstanding:
            return json_error("A matching rule creation is already unresolved.", status_code=409, code="EXTERNAL_OUTCOME_UNKNOWN", details={"operation_id": outstanding.id})
        operation = ExternalOperation(
            user_id=current_user.id,
            operation="rule_create",
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            state="sending",
        )
        db.session.add(operation)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            operation = ExternalOperation.query.filter_by(
                user_id=current_user.id,
                operation="rule_create",
                idempotency_key=idempotency_key,
            ).first()
            if operation and operation.request_fingerprint == fingerprint:
                if operation.state == "succeeded":
                    return json_ok(
                        message="Rule copy already completed.",
                        operation_id=operation.id,
                        created={"id": operation.external_result_id},
                    )
                return json_error(
                    "A matching rule creation is already in progress or requires review.",
                    status_code=409,
                    code="EXTERNAL_OUTCOME_UNKNOWN",
                    details={"operation_id": operation.id},
                )
            return json_error(
                "Idempotency key is already bound to another request.",
                status_code=409,
                code="IDEMPOTENCY_CONFLICT",
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
            if (
                configured_actor_account_id == author_account_id
                or not configured_actor_exc.definitive
                or configured_actor_exc.fallback_kind != "actor"
            ):
                operation.state = "unknown" if configured_actor_exc.outcome == "unknown" else "rejected"
                operation.error_code = "EXTERNAL_OUTCOME_UNKNOWN" if operation.state == "unknown" else "RULE_CREATE_REJECTED"
                db.session.commit()
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
                idempotency_key=idempotency_key,
            )
            created = _create_rule_with_identifier_fallback(
                service,
                target_jira_project_id,
                target_project_key,
                user_actor_payload,
                pat,
            )
            actor_used = author_account_id

        operation.state = "succeeded"
        operation.external_result_id = str((created or {}).get("id") or (created or {}).get("ruleId") or "") or None
        db.session.commit()

        return json_ok(
            message="Rule copied successfully.",
            target_project_key=target_project_key,
            target_project_id=target_jira_project_id,
            target_board_id=target_board_id_int,
            actor_used=actor_used,
            created=created,
            operation_id=operation.id,
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
        status = 409 if getattr(exc, "outcome", None) == "unknown" else 400
        code = "EXTERNAL_OUTCOME_UNKNOWN" if status == 409 else "RULE_CREATE_REJECTED"
        return json_error(safe_error_message("copy the automation rule"), status_code=status, code=code)
    except Exception as exc:
        current_app.logger.exception("Unexpected error in copy_rule: %s", exc)
        return json_error("Unexpected error occurred.", status_code=500)
