"""add epic_key to user_tableau_custom_views

Revision ID: 44a4a3ce3141
Revises: f8954404f3b1
Create Date: 2026-03-24 17:02:02.049873

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "44a4a3ce3141"
down_revision = "f8954404f3b1"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("user_tableau_custom_views")
    }


def upgrade():
    columns = _columns()
    if "epic_key" not in columns:
        op.add_column(
            "user_tableau_custom_views",
            sa.Column("epic_key", sa.String(length=32), nullable=True),
        )
    if "project_key" in columns:
        op.execute(
            "UPDATE user_tableau_custom_views SET epic_key = COALESCE(epic_key, project_key)"
        )
        with op.batch_alter_table("user_tableau_custom_views", schema=None) as batch_op:
            batch_op.drop_column("project_key")


def downgrade():
    columns = _columns()
    if "project_key" not in columns:
        op.add_column(
            "user_tableau_custom_views",
            sa.Column("project_key", sa.String(length=32), nullable=True),
        )
    if "epic_key" in columns:
        op.execute(
            "UPDATE user_tableau_custom_views SET project_key = COALESCE(project_key, epic_key)"
        )
        with op.batch_alter_table("user_tableau_custom_views", schema=None) as batch_op:
            batch_op.drop_column("epic_key")
