from __future__ import annotations

from datetime import UTC, datetime
import uuid

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text

from ....extensions import db


def utc_now() -> datetime:
    return datetime.now(UTC)


def uuid_value() -> str:
    return str(uuid.uuid4())


COMPONENT_KEYS = (
    "core",
    "history",
    "comments",
    "original_commitment",
    "completed_original",
    "total_completed",
    "added_scope",
    "removed_scope",
    "metrics",
)


class JiraSource(db.Model):
    __tablename__ = "jira_sources"
    id = db.Column(db.Integer, primary_key=True)
    source_key = db.Column(db.String(128), nullable=False, unique=True)
    base_url = db.Column(db.String(1024), nullable=False)
    config_fingerprint = db.Column(db.String(64), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)


class JiraScope(db.Model):
    __tablename__ = "jira_scopes"
    id = db.Column(db.String(36), primary_key=True, default=uuid_value)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_id = db.Column(db.Integer, db.ForeignKey("jira_sources.id"), nullable=False)
    credential_epoch = db.Column(db.Integer, nullable=False)
    access_epoch = db.Column(db.Integer, nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source_id", "credential_epoch", "access_epoch",
            name="uq_jira_scope_epochs",
        ),
        Index("ix_jira_scopes_user_active", "user_id", "revoked_at"),
    )


class JiraSprintCatalog(db.Model):
    __tablename__ = "jira_sprint_catalogs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_id = db.Column(db.Integer, db.ForeignKey("jira_sources.id"), nullable=False)
    board_id = db.Column(db.Integer, nullable=False)
    state = db.Column(db.String(24), nullable=False, default="complete")
    item_count = db.Column(db.Integer, nullable=False, default=0)
    verified_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    __table_args__ = (
        UniqueConstraint("user_id", "source_id", "board_id", name="uq_jira_sprint_catalog"),
        CheckConstraint("board_id > 0", name="ck_jira_sprint_catalog_board"),
    )


class JiraPrincipal(db.Model):
    __tablename__ = "jira_principals"
    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey("jira_sources.id"), nullable=False)
    namespace = db.Column(db.String(32), nullable=False, default="dc_key")
    external_id = db.Column(db.String(255), nullable=False)
    display_label = db.Column(db.String(255), nullable=True)
    last_observed_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    __table_args__ = (
        UniqueConstraint("source_id", "namespace", "external_id", name="uq_jira_principal"),
    )


class JiraPrincipalAlias(db.Model):
    __tablename__ = "jira_principal_aliases"
    id = db.Column(db.Integer, primary_key=True)
    principal_id = db.Column(db.Integer, db.ForeignKey("jira_principals.id", ondelete="CASCADE"), nullable=False)
    source_id = db.Column(db.Integer, db.ForeignKey("jira_sources.id"), nullable=False)
    namespace = db.Column(db.String(32), nullable=False)
    alias_value = db.Column(db.String(255), nullable=False)
    normalized_value = db.Column(db.String(255), nullable=False)
    observed_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    valid_from = db.Column(db.DateTime(timezone=True), nullable=True)
    valid_to = db.Column(db.DateTime(timezone=True), nullable=True)
    evidence_kind = db.Column(db.String(32), nullable=False, default="payload")
    ambiguous = db.Column(db.Boolean, nullable=False, default=False)
    __table_args__ = (
        Index("ix_jira_alias_lookup", "source_id", "namespace", "normalized_value"),
    )


class SprintSnapshotSeries(db.Model):
    __tablename__ = "sprint_snapshot_series"
    id = db.Column(db.String(36), primary_key=True, default=uuid_value)
    scope_id = db.Column(db.String(36), db.ForeignKey("jira_scopes.id", ondelete="CASCADE"), nullable=False)
    board_id = db.Column(db.Integer, nullable=False)
    sprint_id = db.Column(db.Integer, nullable=False)
    schema_version = db.Column(db.Integer, nullable=False, default=1)
    query_version = db.Column(db.Integer, nullable=False, default=1)
    calculation_version = db.Column(db.Integer, nullable=False, default=1)
    next_generation = db.Column(db.Integer, nullable=False, default=1)
    active_snapshot_id = db.Column(db.String(36), nullable=True)
    candidate_snapshot_id = db.Column(db.String(36), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "scope_id", "board_id", "sprint_id", "schema_version", "query_version",
            "calculation_version", name="uq_snapshot_series_scope_versions",
        ),
        CheckConstraint("board_id > 0 AND sprint_id > 0", name="ck_snapshot_series_positive_ids"),
        Index("ix_snapshot_series_lookup", "scope_id", "board_id", "sprint_id"),
    )


class SprintSnapshot(db.Model):
    __tablename__ = "sprint_snapshots"
    id = db.Column(db.String(36), primary_key=True, default=uuid_value)
    series_id = db.Column(db.String(36), db.ForeignKey("sprint_snapshot_series.id", ondelete="CASCADE"), nullable=False)
    generation = db.Column(db.Integer, nullable=False)
    sprint_metadata = db.Column(db.JSON, nullable=False, default=dict)
    schema_version = db.Column(db.Integer, nullable=False, default=1)
    query_version = db.Column(db.Integer, nullable=False, default=1)
    calculation_version = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(db.String(24), nullable=False, default="processing")
    response_revision = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    collection_started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    collection_ended_at = db.Column(db.DateTime(timezone=True), nullable=True)
    invalidated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    failure_code = db.Column(db.String(64), nullable=True)
    __table_args__ = (
        UniqueConstraint("series_id", "generation", name="uq_snapshot_generation"),
        CheckConstraint("status IN ('processing','ready','failed','cancelled')", name="ck_snapshot_status"),
        Index("ix_snapshots_series_status", "series_id", "status"),
    )


class SprintComponent(db.Model):
    __tablename__ = "sprint_components"
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.String(36), db.ForeignKey("sprint_snapshots.id", ondelete="CASCADE"), nullable=False)
    component_key = db.Column(db.String(32), nullable=False)
    state = db.Column(db.String(24), nullable=False, default="missing")
    published_revision_id = db.Column(db.Integer, nullable=True)
    next_revision = db.Column(db.Integer, nullable=False, default=1)
    error_code = db.Column(db.String(64), nullable=True)
    __table_args__ = (
        UniqueConstraint("snapshot_id", "component_key", name="uq_snapshot_component"),
        CheckConstraint("state IN ('missing','queued','running','ready','failed','unavailable','cancelled')", name="ck_component_state"),
        Index("ix_components_snapshot_state", "snapshot_id", "state"),
    )


class SprintComponentRevision(db.Model):
    __tablename__ = "sprint_component_revisions"
    id = db.Column(db.Integer, primary_key=True)
    component_id = db.Column(db.Integer, db.ForeignKey("sprint_components.id", ondelete="CASCADE"), nullable=False)
    revision = db.Column(db.Integer, nullable=False)
    state = db.Column(db.String(24), nullable=False, default="staging")
    producer_job_id = db.Column(db.String(36), nullable=True)
    producer_fence = db.Column(db.Integer, nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    expected_count = db.Column(db.Integer, nullable=True)
    received_count = db.Column(db.Integer, nullable=True)
    unique_count = db.Column(db.Integer, nullable=True)
    input_revisions = db.Column(db.JSON, nullable=False, default=dict)
    data_quality = db.Column(db.String(24), nullable=False, default="provisional")
    error_code = db.Column(db.String(64), nullable=True)
    output = db.Column(db.JSON, nullable=False, default=dict)
    __table_args__ = (
        UniqueConstraint("component_id", "revision", name="uq_component_revision"),
        CheckConstraint("state IN ('staging','ready','failed','unavailable','cancelled')", name="ck_component_revision_state"),
    )


class SprintIssueRow(db.Model):
    __tablename__ = "sprint_issue_rows"
    id = db.Column(db.Integer, primary_key=True)
    core_revision_id = db.Column(db.Integer, db.ForeignKey("sprint_component_revisions.id", ondelete="CASCADE"), nullable=False)
    jira_issue_id = db.Column(db.String(64), nullable=False)
    issue_key = db.Column(db.String(255), nullable=True)
    principal_id = db.Column(db.Integer, db.ForeignKey("jira_principals.id"), nullable=True)
    payload = db.Column(db.JSON, nullable=False)
    __table_args__ = (
        UniqueConstraint("core_revision_id", "jira_issue_id", name="uq_core_issue"),
        Index("ix_core_issue_principal", "core_revision_id", "principal_id", "jira_issue_id"),
        Index("ix_core_issue_id", "core_revision_id", "jira_issue_id"),
    )


class SprintHistoryRow(db.Model):
    __tablename__ = "sprint_history_rows"
    id = db.Column(db.Integer, primary_key=True)
    history_revision_id = db.Column(db.Integer, db.ForeignKey("sprint_component_revisions.id", ondelete="CASCADE"), nullable=False)
    jira_issue_id = db.Column(db.String(64), nullable=False)
    principal_id = db.Column(db.Integer, db.ForeignKey("jira_principals.id"), nullable=True)
    payload = db.Column(db.JSON, nullable=False)
    __table_args__ = (UniqueConstraint("history_revision_id", "jira_issue_id", name="uq_history_issue"),)


class SprintCommentRow(db.Model):
    __tablename__ = "sprint_comment_rows"
    id = db.Column(db.Integer, primary_key=True)
    comments_revision_id = db.Column(db.Integer, db.ForeignKey("sprint_component_revisions.id", ondelete="CASCADE"), nullable=False)
    jira_issue_id = db.Column(db.String(64), nullable=False)
    jira_comment_id = db.Column(db.String(64), nullable=False)
    principal_id = db.Column(db.Integer, db.ForeignKey("jira_principals.id"), nullable=True)
    created_at_source = db.Column(db.String(64), nullable=True)
    visibility_fingerprint = db.Column(db.String(64), nullable=True)
    __table_args__ = (UniqueConstraint("comments_revision_id", "jira_issue_id", "jira_comment_id", name="uq_comment_membership"),)


class SprintMetricMembership(db.Model):
    __tablename__ = "sprint_metric_memberships"
    id = db.Column(db.Integer, primary_key=True)
    category_revision_id = db.Column(db.Integer, db.ForeignKey("sprint_component_revisions.id", ondelete="CASCADE"), nullable=False)
    jira_issue_id = db.Column(db.String(64), nullable=False)
    issue_key = db.Column(db.String(255), nullable=True)
    project_id = db.Column(db.String(64), nullable=True)
    project_key = db.Column(db.String(64), nullable=True)
    story_points = db.Column(db.Float, nullable=True)
    source_updated_at = db.Column(db.String(64), nullable=True)
    __table_args__ = (UniqueConstraint("category_revision_id", "jira_issue_id", name="uq_metric_issue"),)


class BackgroundJob(db.Model):
    __tablename__ = "background_jobs"
    id = db.Column(db.String(36), primary_key=True, default=uuid_value)
    job_type = db.Column(db.String(32), nullable=False)
    scope_id = db.Column(db.String(36), db.ForeignKey("jira_scopes.id", ondelete="CASCADE"), nullable=False)
    snapshot_id = db.Column(db.String(36), db.ForeignKey("sprint_snapshots.id", ondelete="CASCADE"), nullable=True)
    component_key = db.Column(db.String(32), nullable=True)
    dedupe_key = db.Column(db.String(255), nullable=False)
    state = db.Column(db.String(24), nullable=False, default="queued")
    lane = db.Column(db.String(16), nullable=False, default="core")
    priority = db.Column(db.Integer, nullable=False, default=100)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    available_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=3)
    resume_kind = db.Column(db.String(16), nullable=False, default="new")
    cursor = db.Column(db.JSON, nullable=False, default=dict)
    lease_owner = db.Column(db.String(36), nullable=True)
    lease_until = db.Column(db.DateTime(timezone=True), nullable=True)
    fence = db.Column(db.Integer, nullable=False, default=0)
    leader_epoch = db.Column(db.Integer, nullable=True)
    error_code = db.Column(db.String(64), nullable=True)
    request_id = db.Column(db.String(64), nullable=True)
    __table_args__ = (
        CheckConstraint("state IN ('queued','running','retry_wait','succeeded','failed','cancelled')", name="ck_job_state"),
        Index("ix_jobs_queue", "lane", "state", "available_at", "priority", "created_at"),
        Index("ix_jobs_dedupe", "dedupe_key", "state"),
    )


class WorkerLeader(db.Model):
    __tablename__ = "worker_leaders"
    name = db.Column(db.String(64), primary_key=True)
    owner = db.Column(db.String(36), nullable=False)
    epoch = db.Column(db.Integer, nullable=False, default=1)
    lease_until = db.Column(db.DateTime(timezone=True), nullable=False)
    last_heartbeat = db.Column(db.DateTime(timezone=True), nullable=False)
    application_version = db.Column(db.String(64), nullable=True)
    schema_version = db.Column(db.String(64), nullable=True)


class JiraRequestSlot(db.Model):
    __tablename__ = "jira_request_slots"
    source_id = db.Column(db.Integer, db.ForeignKey("jira_sources.id"), primary_key=True)
    slot_number = db.Column(db.Integer, primary_key=True)
    slot_class = db.Column(db.String(16), nullable=False)
    owner_token = db.Column(db.String(36), nullable=True)
    lease_until = db.Column(db.DateTime(timezone=True), nullable=True)
    fence = db.Column(db.Integer, nullable=False, default=0)


class ReportView(db.Model):
    __tablename__ = "report_views"
    id = db.Column(db.String(36), primary_key=True, default=uuid_value)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    auth_session_id = db.Column(db.String(36), db.ForeignKey("auth_sessions.id", ondelete="CASCADE"), nullable=True)
    scope_id = db.Column(db.String(36), db.ForeignKey("jira_scopes.id", ondelete="CASCADE"), nullable=False)
    snapshot_id = db.Column(db.String(36), db.ForeignKey("sprint_snapshots.id", ondelete="CASCADE"), nullable=False)
    client_action_nonce = db.Column(db.String(64), nullable=False)
    purpose = db.Column(db.String(16), nullable=False, default="view")
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    access_state = db.Column(db.JSON, nullable=False, default=dict)
    verified_revisions = db.Column(db.JSON, nullable=False, default=dict)
    error_code = db.Column(db.String(64), nullable=True)
    __table_args__ = (
        UniqueConstraint("auth_session_id", "client_action_nonce", name="uq_report_view_action"),
        Index("ix_report_views_snapshot_user", "snapshot_id", "user_id", "expires_at"),
    )


class RateLimitBucket(db.Model):
    __tablename__ = "rate_limit_buckets"
    operation = db.Column(db.String(64), primary_key=True)
    subject_key = db.Column(db.String(64), primary_key=True)
    window_start = db.Column(db.Integer, primary_key=True)
    count = db.Column(db.Integer, nullable=False, default=0)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)


class ExternalOperation(db.Model):
    __tablename__ = "external_operations"
    id = db.Column(db.String(36), primary_key=True, default=uuid_value)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scope_id = db.Column(db.String(36), db.ForeignKey("jira_scopes.id", ondelete="SET NULL"), nullable=True)
    operation = db.Column(db.String(64), nullable=False)
    idempotency_key = db.Column(db.String(128), nullable=False)
    request_fingerprint = db.Column(db.String(64), nullable=False)
    state = db.Column(db.String(16), nullable=False, default="prepared")
    external_result_id = db.Column(db.String(255), nullable=True)
    error_code = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    __table_args__ = (
        UniqueConstraint("user_id", "operation", "idempotency_key", name="uq_external_operation_key"),
        CheckConstraint("state IN ('prepared','sending','succeeded','rejected','unknown')", name="ck_external_operation_state"),
        Index("ix_external_operation_fingerprint", "user_id", "operation", "request_fingerprint", "state"),
    )
