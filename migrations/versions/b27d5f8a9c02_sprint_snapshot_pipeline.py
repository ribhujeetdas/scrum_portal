"""durable sprint snapshot and worker pipeline

Revision ID: b27d5f8a9c02
Revises: a18c9e4d7b01
"""
from alembic import op
import sqlalchemy as sa


revision = "b27d5f8a9c02"
down_revision = "a18c9e4d7b01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("jira_sources",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("source_key", sa.String(128), nullable=False, unique=True),
        sa.Column("base_url", sa.String(1024), nullable=False), sa.Column("config_fingerprint", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("jira_scopes",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("jira_sources.id"), nullable=False), sa.Column("credential_epoch", sa.Integer(), nullable=False),
        sa.Column("access_epoch", sa.Integer(), nullable=False), sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "source_id", "credential_epoch", "access_epoch", name="uq_jira_scope_epochs"))
    op.create_index("ix_jira_scopes_user_active", "jira_scopes", ["user_id", "revoked_at"])
    op.create_table("jira_sprint_catalogs",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("jira_sources.id"), nullable=False), sa.Column("board_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False), sa.Column("item_count", sa.Integer(), nullable=False), sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("board_id > 0", name="ck_jira_sprint_catalog_board"), sa.UniqueConstraint("user_id", "source_id", "board_id", name="uq_jira_sprint_catalog"))
    op.create_table("jira_principals",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("source_id", sa.Integer(), sa.ForeignKey("jira_sources.id"), nullable=False),
        sa.Column("namespace", sa.String(32), nullable=False), sa.Column("external_id", sa.String(255), nullable=False), sa.Column("display_label", sa.String(255)),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("source_id", "namespace", "external_id", name="uq_jira_principal"))
    op.create_table("jira_principal_aliases",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("principal_id", sa.Integer(), sa.ForeignKey("jira_principals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("jira_sources.id"), nullable=False), sa.Column("namespace", sa.String(32), nullable=False),
        sa.Column("alias_value", sa.String(255), nullable=False), sa.Column("normalized_value", sa.String(255), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("valid_from", sa.DateTime(timezone=True)), sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("evidence_kind", sa.String(32), nullable=False), sa.Column("ambiguous", sa.Boolean(), nullable=False))
    op.create_index("ix_jira_alias_lookup", "jira_principal_aliases", ["source_id", "namespace", "normalized_value"])
    op.create_table("sprint_snapshot_series",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("scope_id", sa.String(36), sa.ForeignKey("jira_scopes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("board_id", sa.Integer(), nullable=False), sa.Column("sprint_id", sa.Integer(), nullable=False), sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("query_version", sa.Integer(), nullable=False), sa.Column("calculation_version", sa.Integer(), nullable=False), sa.Column("next_generation", sa.Integer(), nullable=False),
        sa.Column("active_snapshot_id", sa.String(36)), sa.Column("candidate_snapshot_id", sa.String(36)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("board_id > 0 AND sprint_id > 0", name="ck_snapshot_series_positive_ids"),
        sa.UniqueConstraint("scope_id", "board_id", "sprint_id", "schema_version", "query_version", "calculation_version", name="uq_snapshot_series_scope_versions"))
    op.create_index("ix_snapshot_series_lookup", "sprint_snapshot_series", ["scope_id", "board_id", "sprint_id"])
    op.create_table("sprint_snapshots",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("series_id", sa.String(36), sa.ForeignKey("sprint_snapshot_series.id", ondelete="CASCADE"), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False), sa.Column("sprint_metadata", sa.JSON(), nullable=False), sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("query_version", sa.Integer(), nullable=False), sa.Column("calculation_version", sa.Integer(), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("response_revision", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("collection_started_at", sa.DateTime(timezone=True)),
        sa.Column("collection_ended_at", sa.DateTime(timezone=True)), sa.Column("invalidated_at", sa.DateTime(timezone=True)), sa.Column("failure_code", sa.String(64)),
        sa.CheckConstraint("status IN ('processing','ready','failed','cancelled')", name="ck_snapshot_status"), sa.UniqueConstraint("series_id", "generation", name="uq_snapshot_generation"))
    op.create_index("ix_snapshots_series_status", "sprint_snapshots", ["series_id", "status"])
    op.create_table("sprint_components",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("sprint_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("component_key", sa.String(32), nullable=False), sa.Column("state", sa.String(24), nullable=False), sa.Column("published_revision_id", sa.Integer()),
        sa.Column("next_revision", sa.Integer(), nullable=False), sa.Column("error_code", sa.String(64)),
        sa.CheckConstraint("state IN ('missing','queued','running','ready','failed','unavailable','cancelled')", name="ck_component_state"),
        sa.UniqueConstraint("snapshot_id", "component_key", name="uq_snapshot_component"))
    op.create_index("ix_components_snapshot_state", "sprint_components", ["snapshot_id", "state"])
    op.create_table("sprint_component_revisions",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("component_id", sa.Integer(), sa.ForeignKey("sprint_components.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("state", sa.String(24), nullable=False), sa.Column("producer_job_id", sa.String(36)),
        sa.Column("producer_fence", sa.Integer()), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("expected_count", sa.Integer()), sa.Column("received_count", sa.Integer()), sa.Column("unique_count", sa.Integer()),
        sa.Column("input_revisions", sa.JSON(), nullable=False), sa.Column("data_quality", sa.String(24), nullable=False), sa.Column("error_code", sa.String(64)), sa.Column("output", sa.JSON(), nullable=False),
        sa.CheckConstraint("state IN ('staging','ready','failed','unavailable','cancelled')", name="ck_component_revision_state"), sa.UniqueConstraint("component_id", "revision", name="uq_component_revision"))
    op.create_table("sprint_issue_rows",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("core_revision_id", sa.Integer(), sa.ForeignKey("sprint_component_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jira_issue_id", sa.String(64), nullable=False), sa.Column("issue_key", sa.String(255)), sa.Column("principal_id", sa.Integer(), sa.ForeignKey("jira_principals.id")),
        sa.Column("payload", sa.JSON(), nullable=False), sa.UniqueConstraint("core_revision_id", "jira_issue_id", name="uq_core_issue"))
    op.create_index("ix_core_issue_principal", "sprint_issue_rows", ["core_revision_id", "principal_id", "jira_issue_id"])
    op.create_index("ix_core_issue_id", "sprint_issue_rows", ["core_revision_id", "jira_issue_id"])
    op.create_table("sprint_history_rows",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("history_revision_id", sa.Integer(), sa.ForeignKey("sprint_component_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jira_issue_id", sa.String(64), nullable=False), sa.Column("principal_id", sa.Integer(), sa.ForeignKey("jira_principals.id")), sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("history_revision_id", "jira_issue_id", name="uq_history_issue"))
    op.create_table("sprint_comment_rows",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("comments_revision_id", sa.Integer(), sa.ForeignKey("sprint_component_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jira_issue_id", sa.String(64), nullable=False), sa.Column("jira_comment_id", sa.String(64), nullable=False), sa.Column("principal_id", sa.Integer(), sa.ForeignKey("jira_principals.id")),
        sa.Column("created_at_source", sa.String(64)), sa.Column("visibility_fingerprint", sa.String(64)), sa.UniqueConstraint("comments_revision_id", "jira_issue_id", "jira_comment_id", name="uq_comment_membership"))
    op.create_table("sprint_metric_memberships",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("category_revision_id", sa.Integer(), sa.ForeignKey("sprint_component_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jira_issue_id", sa.String(64), nullable=False), sa.Column("issue_key", sa.String(255)), sa.Column("project_id", sa.String(64)), sa.Column("project_key", sa.String(64)),
        sa.Column("story_points", sa.Float()), sa.Column("source_updated_at", sa.String(64)), sa.UniqueConstraint("category_revision_id", "jira_issue_id", name="uq_metric_issue"))
    op.create_table("background_jobs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("job_type", sa.String(32), nullable=False), sa.Column("scope_id", sa.String(36), sa.ForeignKey("jira_scopes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("sprint_snapshots.id", ondelete="CASCADE")), sa.Column("component_key", sa.String(32)), sa.Column("dedupe_key", sa.String(255), nullable=False),
        sa.Column("state", sa.String(24), nullable=False), sa.Column("lane", sa.String(16), nullable=False), sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("max_attempts", sa.Integer(), nullable=False), sa.Column("resume_kind", sa.String(16), nullable=False), sa.Column("cursor", sa.JSON(), nullable=False),
        sa.Column("lease_owner", sa.String(36)), sa.Column("lease_until", sa.DateTime(timezone=True)), sa.Column("fence", sa.Integer(), nullable=False), sa.Column("leader_epoch", sa.Integer()),
        sa.Column("error_code", sa.String(64)), sa.Column("request_id", sa.String(64)), sa.CheckConstraint("state IN ('queued','running','retry_wait','succeeded','failed','cancelled')", name="ck_job_state"))
    op.create_index("ix_jobs_queue", "background_jobs", ["lane", "state", "available_at", "priority", "created_at"])
    op.create_index("ix_jobs_dedupe", "background_jobs", ["dedupe_key", "state"])
    op.create_table("worker_leaders",
        sa.Column("name", sa.String(64), primary_key=True), sa.Column("owner", sa.String(36), nullable=False), sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False), sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=False),
        sa.Column("application_version", sa.String(64)), sa.Column("schema_version", sa.String(64)))
    op.create_table("jira_request_slots",
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("jira_sources.id"), primary_key=True), sa.Column("slot_number", sa.Integer(), primary_key=True),
        sa.Column("slot_class", sa.String(16), nullable=False), sa.Column("owner_token", sa.String(36)), sa.Column("lease_until", sa.DateTime(timezone=True)), sa.Column("fence", sa.Integer(), nullable=False))
    op.create_table("report_views",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("auth_session_id", sa.String(36), sa.ForeignKey("auth_sessions.id", ondelete="CASCADE")), sa.Column("scope_id", sa.String(36), sa.ForeignKey("jira_scopes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("sprint_snapshots.id", ondelete="CASCADE"), nullable=False), sa.Column("client_action_nonce", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("access_state", sa.JSON(), nullable=False), sa.Column("verified_revisions", sa.JSON(), nullable=False), sa.Column("error_code", sa.String(64)),
        sa.UniqueConstraint("auth_session_id", "client_action_nonce", name="uq_report_view_action"))
    op.create_index("ix_report_views_snapshot_user", "report_views", ["snapshot_id", "user_id", "expires_at"])
    op.create_table("rate_limit_buckets",
        sa.Column("operation", sa.String(64), primary_key=True), sa.Column("subject_key", sa.String(64), primary_key=True), sa.Column("window_start", sa.Integer(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_rate_limit_buckets_expires_at", "rate_limit_buckets", ["expires_at"])
    op.create_table("external_operations",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope_id", sa.String(36), sa.ForeignKey("jira_scopes.id", ondelete="SET NULL")), sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False), sa.Column("request_fingerprint", sa.String(64), nullable=False), sa.Column("state", sa.String(16), nullable=False),
        sa.Column("external_result_id", sa.String(255)), sa.Column("error_code", sa.String(64)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state IN ('prepared','sending','succeeded','rejected','unknown')", name="ck_external_operation_state"), sa.UniqueConstraint("user_id", "operation", "idempotency_key", name="uq_external_operation_key"))
    op.create_index("ix_external_operation_fingerprint", "external_operations", ["user_id", "operation", "request_fingerprint", "state"])


def downgrade():
    for table in ("external_operations", "rate_limit_buckets", "report_views", "jira_request_slots", "worker_leaders", "background_jobs", "sprint_metric_memberships", "sprint_comment_rows", "sprint_history_rows", "sprint_issue_rows", "sprint_component_revisions", "sprint_components", "sprint_snapshots", "sprint_snapshot_series", "jira_principal_aliases", "jira_principals", "jira_sprint_catalogs", "jira_scopes", "jira_sources"):
        op.drop_table(table)
