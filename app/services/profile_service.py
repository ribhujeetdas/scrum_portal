# app/services/profile_service.py
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from ..extensions import db
from ..models import UserProject, UserBoard, UserBoardSprint
from ..utils.log import log


class ProfileServiceError(Exception):
    """Raised when a profile operation fails or is invalid."""


@dataclass(frozen=True)
class DeleteProjectRequest:
    user_id: int
    project_key: str


@dataclass(frozen=True)
class DeleteBoardRequest:
    user_id: int
    project_key: str
    board_id: int


class ProfileService:
    """
    OOP service layer for Profile operations (delete project / delete board).
    Keeps route handler logic thin and consistent.
    """

    @staticmethod
    def _norm_project_key(project_key: str) -> str:
        return (project_key or "").strip().upper()

    def delete_project(self, req: DeleteProjectRequest) -> int:
        """
        Deletes a project and all its boards.
        Also clears cached sprint rows for the user for those boards.
        Returns: number of boards removed.
        """
        project_key = self._norm_project_key(req.project_key)
        if not project_key:
            raise ProfileServiceError("Project key is required.")

        proj = (
            UserProject.query
            .filter_by(user_id=req.user_id, project_key=project_key)
            .first()
        )
        if not proj:
            raise ProfileServiceError("Project not found for your account.")

        board_ids = [b.board_id for b in (proj.boards or [])]
        boards_removed = len(board_ids)

        try:
            if board_ids:
                UserBoardSprint.query.filter(
                    UserBoardSprint.user_id == req.user_id,
                    UserBoardSprint.board_id.in_(board_ids),
                ).delete(synchronize_session=False)

            # cascades to boards due to relationship config
            db.session.delete(proj)
            db.session.commit()

            log.info(
                "Project deleted user_id=%s project=%s boards_removed=%s",
                req.user_id, project_key, boards_removed
            )
            return boards_removed

        except SQLAlchemyError as exc:
            db.session.rollback()
            log.exception(
                "Delete project failed user_id=%s project=%s err=%s",
                req.user_id, project_key, exc
            )
            raise ProfileServiceError(
                "Failed to delete project due to a database error.") from exc

    def delete_board(self, req: DeleteBoardRequest) -> None:
        """
        Deletes a board under a project.
        Also clears cached sprint rows for that board.
        """
        project_key = self._norm_project_key(req.project_key)
        if not project_key:
            raise ProfileServiceError("Project key is required.")
        if req.board_id <= 0:
            raise ProfileServiceError("Board ID must be a positive integer.")

        proj = (
            UserProject.query
            .filter_by(user_id=req.user_id, project_key=project_key)
            .first()
        )
        if not proj:
            raise ProfileServiceError("Project not found for your account.")

        board = (
            UserBoard.query
            .filter_by(project_id=proj.id, board_id=req.board_id)
            .first()
        )
        if not board:
            raise ProfileServiceError("Board not found for this project.")

        try:
            UserBoardSprint.query.filter_by(
                user_id=req.user_id, board_id=req.board_id
            ).delete(synchronize_session=False)

            db.session.delete(board)
            db.session.commit()

            log.info(
                "Board deleted user_id=%s project=%s board_id=%s",
                req.user_id, project_key, req.board_id
            )

        except SQLAlchemyError as exc:
            db.session.rollback()
            log.exception(
                "Delete board failed user_id=%s project=%s board_id=%s err=%s",
                req.user_id, project_key, req.board_id, exc
            )
            raise ProfileServiceError(
                "Failed to delete board due to a database error.") from exc
