# app/models.py
from __future__ import annotations

from datetime import datetime
from flask_login import UserMixin
from sqlalchemy import UniqueConstraint
from werkzeug.security import generate_password_hash, check_password_hash

from .extensions import db, login_manager


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    # Jira profile fields
    eid = db.Column(db.String(64), unique=True,
                    nullable=False)  # response["name"]
    jira_key = db.Column(db.String(64), nullable=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    display_name = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    deleted = db.Column(db.Boolean, nullable=False, default=False)
    timezone = db.Column(db.String(64), nullable=True)
    locale = db.Column(db.String(64), nullable=True)

    # Credential storage
    password_hash = db.Column(db.String(255), nullable=False)

    # Encrypted PAT for "enterprise agile jira"
    jira_pat_enc = db.Column(db.LargeBinary, nullable=True)

    # -----------------------
    # Tableau PAT storage + identity (single definitive set)
    # -----------------------
    tableau_pat_name = db.Column(db.String(128), nullable=True)
    tableau_pat_secret_enc = db.Column(db.LargeBinary, nullable=True)
    tableau_site_id = db.Column(db.String(64), nullable=True)
    tableau_user_id = db.Column(db.String(64), nullable=True)
    tableau_content_url = db.Column(db.String(255), nullable=True)
    tableau_email = db.Column(db.String(255), nullable=True)
    # Tableau "name" stored as EID
    tableau_eid = db.Column(db.String(128), nullable=True)

    created_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    # Relationships
    projects = db.relationship(
        "UserProject",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class UserProject(db.Model):
    __tablename__ = "user_projects"
    __table_args__ = (
        UniqueConstraint("user_id", "project_key", name="uq_user_project_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # Primary/entered project key (stored uppercase)
    project_key = db.Column(db.String(32), nullable=False)

    admin_projects = db.Column(db.Boolean, nullable=False, default=False)

    # Jira numeric project id (optional, set lazily by automation flow)
    project_id = db.Column(db.Integer, nullable=True)

    # NEW: capture "Product Area" project key discovered from board/{boardId}/project
    # This is kept separate from project_key so existing behavior does not break.
    epic_key = db.Column(db.String(32), nullable=True)

    created_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    user = db.relationship("User", back_populates="projects")

    boards = db.relationship(
        "UserBoard",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class UserBoard(db.Model):
    __tablename__ = "user_boards"
    __table_args__ = (
        UniqueConstraint("project_id", "board_id", name="uq_project_board_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey(
        "user_projects.id"), nullable=False)

    board_id = db.Column(db.Integer, nullable=False)
    board_name = db.Column(db.String(255), nullable=False)
    board_type = db.Column(db.String(32), nullable=True)
    board_url = db.Column(db.String(1024), nullable=True)

    created_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    project = db.relationship("UserProject", back_populates="boards")


class UserBoardSprint(db.Model):
    __tablename__ = "user_board_sprints"
    __table_args__ = (
        db.UniqueConstraint("user_id", "board_id",
                            "sprint_id", name="uq_user_board_sprint"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # board_id is stable globally in Jira Agile
    board_id = db.Column(db.Integer, nullable=False)

    sprint_id = db.Column(db.Integer, nullable=False)
    sprint_name = db.Column(db.String(255), nullable=False)
    sprint_state = db.Column(db.String(32), nullable=False)
    sprint_url = db.Column(db.String(1024), nullable=True)

    start_date = db.Column(db.String(64), nullable=True)
    end_date = db.Column(db.String(64), nullable=True)
    complete_date = db.Column(db.String(64), nullable=True)
    activated_date = db.Column(db.String(64), nullable=True)
    origin_board_id = db.Column(db.Integer, nullable=True)
    goal = db.Column(db.Text, nullable=True)
    synced = db.Column(db.Boolean, nullable=True)
    auto_start_stop = db.Column(db.Boolean, nullable=True)

    created_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)


class UserTableauCustomView(db.Model):
    __tablename__ = "user_tableau_custom_views"
    __table_args__ = (
        UniqueConstraint("user_id", "custom_view_id",
                         name="uq_user_custom_view"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # Custom view LUID/UUID
    custom_view_id = db.Column(db.String(64), nullable=False)
    custom_view_name = db.Column(db.String(255), nullable=True)
    epic_key = db.Column(db.String(32), nullable=True)

    # Helpful pointers (optional)
    view_id = db.Column(db.String(64), nullable=True)
    view_name = db.Column(db.String(255), nullable=True)
    workbook_id = db.Column(db.String(64), nullable=True)
    workbook_name = db.Column(db.String(255), nullable=True)
    shared = db.Column(db.Boolean, nullable=True)

    created_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))
