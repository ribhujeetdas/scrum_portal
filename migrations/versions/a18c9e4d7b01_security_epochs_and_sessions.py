"""security epochs and server-side auth sessions

Revision ID: a18c9e4d7b01
Revises: 9c2a1f7b6d10
"""
from alembic import op
import sqlalchemy as sa


revision = "a18c9e4d7b01"
down_revision = "9c2a1f7b6d10"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite supports additive columns with a constant non-null default. Avoid
    # table-copy batch mode here so existing foreign keys and Alembic's version
    # transaction remain intact.
    op.add_column("users", sa.Column("session_epoch", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("users", sa.Column("jira_credential_epoch", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("users", sa.Column("access_epoch", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_epoch", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_auth_sessions_user_revoked", "auth_sessions", ["user_id", "revoked_at"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade():
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_revoked", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("access_epoch")
        batch.drop_column("jira_credential_epoch")
        batch.drop_column("session_epoch")
