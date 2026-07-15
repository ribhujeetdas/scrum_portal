"""add epic_key to user_projects

Revision ID: c3d00bc3ae67
Revises:
Create Date: 2026-03-18 18:35:02.656494

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c3d00bc3ae67"
down_revision = None
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("user_projects")}


def upgrade():
    if "epic_key" not in _columns():
        with op.batch_alter_table("user_projects", schema=None) as batch_op:
            batch_op.add_column(sa.Column("epic_key", sa.String(length=32), nullable=True))


def downgrade():
    if "epic_key" in _columns():
        with op.batch_alter_table("user_projects", schema=None) as batch_op:
            batch_op.drop_column("epic_key")
