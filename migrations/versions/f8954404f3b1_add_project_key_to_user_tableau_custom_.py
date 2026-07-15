"""add project_key to user_tableau_custom_views

Revision ID: f8954404f3b1
Revises: c3d00bc3ae67
Create Date: 2026-03-24 15:34:22.452609

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f8954404f3b1"
down_revision = "c3d00bc3ae67"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("user_tableau_custom_views")
    }


def upgrade():
    if "project_key" not in _columns():
        with op.batch_alter_table("user_tableau_custom_views", schema=None) as batch_op:
            batch_op.add_column(sa.Column("project_key", sa.String(length=32), nullable=True))


def downgrade():
    if "project_key" in _columns():
        with op.batch_alter_table("user_tableau_custom_views", schema=None) as batch_op:
            batch_op.drop_column("project_key")
