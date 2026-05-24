"""phase7 project_id and lookup indexes

Revision ID: 9c2a1f7b6d10
Revises: 44a4a3ce3141
Create Date: 2026-05-24 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "9c2a1f7b6d10"
down_revision = "44a4a3ce3141"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade():
    if "project_id" not in _columns("user_projects"):
        with op.batch_alter_table("user_projects", schema=None) as batch_op:
            batch_op.add_column(sa.Column("project_id", sa.Integer(), nullable=True))

    user_project_indexes = _indexes("user_projects")
    if "ix_user_projects_project_id" not in user_project_indexes:
        op.create_index(
            "ix_user_projects_project_id",
            "user_projects",
            ["project_id"],
            unique=False,
        )

    user_board_indexes = _indexes("user_boards")
    if "ix_user_boards_board_id" not in user_board_indexes:
        op.create_index(
            "ix_user_boards_board_id",
            "user_boards",
            ["board_id"],
            unique=False,
        )

    tableau_indexes = _indexes("user_tableau_custom_views")
    if "ix_user_tableau_custom_views_user_updated" not in tableau_indexes:
        op.create_index(
            "ix_user_tableau_custom_views_user_updated",
            "user_tableau_custom_views",
            ["user_id", "updated_at"],
            unique=False,
        )


def downgrade():
    tableau_indexes = _indexes("user_tableau_custom_views")
    if "ix_user_tableau_custom_views_user_updated" in tableau_indexes:
        op.drop_index(
            "ix_user_tableau_custom_views_user_updated",
            table_name="user_tableau_custom_views",
        )

    user_board_indexes = _indexes("user_boards")
    if "ix_user_boards_board_id" in user_board_indexes:
        op.drop_index("ix_user_boards_board_id", table_name="user_boards")

    user_project_indexes = _indexes("user_projects")
    if "ix_user_projects_project_id" in user_project_indexes:
        op.drop_index("ix_user_projects_project_id", table_name="user_projects")

    if "project_id" in _columns("user_projects"):
        with op.batch_alter_table("user_projects", schema=None) as batch_op:
            batch_op.drop_column("project_id")
