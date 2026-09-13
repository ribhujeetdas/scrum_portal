"""Add private append-only sprint review records.

Revision ID: d48e6b9c0d03
Revises: b27d5f8a9c02
"""
from alembic import op
import sqlalchemy as sa

revision = 'd48e6b9c0d03'
down_revision = 'b27d5f8a9c02'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sprint_review_records',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('source_id', sa.Integer(), sa.ForeignKey('jira_sources.id'), nullable=False),
        sa.Column('board_id', sa.Integer(), nullable=False), sa.Column('sprint_id', sa.Integer(), nullable=False),
        sa.Column('record_key', sa.String(80), nullable=False), sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False), sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'source_id', 'board_id', 'sprint_id', 'record_key', 'revision', name='uq_sprint_review_revision'),
        sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_sprint_review_idempotency'))
    op.create_index('ix_sprint_review_scope', 'sprint_review_records', ['user_id', 'source_id', 'board_id', 'sprint_id'])


def downgrade():
    # Feature rollback is a flag change; preserve human records on schema rollback.
    pass
