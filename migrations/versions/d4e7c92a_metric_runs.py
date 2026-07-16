"""Add persisted Sprint metric runs.

Revision ID: d4e7c92a
Revises: b6f3a9c2d410
Create Date: 2026-07-16 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "d4e7c92a"
down_revision = "b6f3a9c2d410"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    if "user_sprint_metric_runs" in _tables():
        return

    op.create_table(
        "user_sprint_metric_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("board_id", sa.Integer(), nullable=False),
        sa.Column("sprint_id", sa.Integer(), nullable=False),
        sa.Column("metrics_version", sa.String(length=32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("total_sp", sa.Float(), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("progress_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("cache_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name="ck_metric_runs_attempts"),
        sa.CheckConstraint("generation >= 1", name="ck_metric_runs_generation"),
        sa.CheckConstraint(
            "status IN ('queued','running','partial','succeeded','failed','interrupted')",
            name="ck_metric_runs_status",
        ),
        sa.CheckConstraint("total_count >= 0", name="ck_metric_runs_total_count"),
        sa.CheckConstraint("total_sp >= 0", name="ck_metric_runs_total_sp"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_metric_runs_user_sprint",
        "user_sprint_metric_runs",
        ["user_id", "board_id", "sprint_id", "metrics_version", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_metric_runs_status_updated",
        "user_sprint_metric_runs",
        ["status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_metric_runs_cache",
        "user_sprint_metric_runs",
        ["user_id", "board_id", "sprint_id", "cache_expires_at"],
        unique=False,
    )


def downgrade():
    if "user_sprint_metric_runs" in _tables():
        op.drop_table("user_sprint_metric_runs")
