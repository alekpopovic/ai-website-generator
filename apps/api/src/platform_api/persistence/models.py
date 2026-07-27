"""Initial PostgreSQL-owned application records."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from platform_api.persistence.base import (
    Base,
    OptimisticVersionMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from platform_api.persistence.json import JsonValue, SafeJSONB


class User(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Locally authenticated platform identity."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="status_allowed"),
        Index("ix_users_email", "email", unique=True),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(back_populates="user")
    projects: Mapped[list[Project]] = relationship(back_populates="owner")


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Hashed refresh-token lifecycle record; plaintext tokens are never persisted."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'revoked', 'expired')", name="status_allowed"),
        Index("ix_refresh_tokens_user_id_status", "user_id", "status"),
        UniqueConstraint("token_hash"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    family_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_token_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    client_metadata: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class AuthActionToken(UUIDPrimaryKeyMixin, Base):
    """Hashed, single-use email verification or password-reset token."""

    __tablename__ = "auth_action_tokens"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('email_verification', 'password_reset')", name="purpose_allowed"
        ),
        UniqueConstraint("token_hash"),
        Index("ix_auth_action_tokens_user_id_purpose", "user_id", "purpose"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class Project(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """User-editable website-generation project metadata."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'archived')", name="status_allowed"),
        Index("ix_projects_owner_id_updated_at", "owner_id", "updated_at"),
        UniqueConstraint("owner_id", "slug"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2_000))
    default_language: Mapped[str] = mapped_column(String(35), nullable=False, default="en")
    default_industry: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    settings: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    owner: Mapped[User] = relationship(back_populates="projects")
    scan_campaigns: Mapped[list[ScanCampaign]] = relationship(back_populates="project")


SCAN_CAMPAIGN_STATUSES = (
    "draft",
    "queued",
    "running",
    "pausing",
    "paused",
    "cancelling",
    "cancelled",
    "succeeded",
    "partially_succeeded",
    "failed",
)


class ScanCampaign(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """User-configured, project-owned scan orchestration record."""

    __tablename__ = "scan_campaigns"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'draft', 'queued', 'running', 'pausing', 'paused', 'cancelling', "
            "'cancelled', 'succeeded', 'partially_succeeded', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint(
            "max_discovered_pages_per_domain BETWEEN 1 AND 10000", name="max_discovered_pages_valid"
        ),
        CheckConstraint(
            "max_visual_pages_per_domain BETWEEN 0 AND 1000", name="max_visual_pages_valid"
        ),
        CheckConstraint("maximum_crawl_depth BETWEEN 0 AND 20", name="crawl_depth_valid"),
        CheckConstraint(
            "per_domain_concurrency BETWEEN 1 AND 32", name="per_domain_concurrency_valid"
        ),
        CheckConstraint("crawl_delay_seconds BETWEEN 0 AND 60", name="crawl_delay_valid"),
        CheckConstraint("overall_concurrency BETWEEN 1 AND 128", name="overall_concurrency_valid"),
        CheckConstraint("workflow_attempt >= 0", name="workflow_attempt_non_negative"),
        Index("ix_scan_campaigns_project_id_updated_at", "project_id", "updated_at"),
        Index("ix_scan_campaigns_project_id_status", "project_id", "status"),
        UniqueConstraint("project_id", "name"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    authorization_attested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    respect_robots_txt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_discovered_pages_per_domain: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100
    )
    max_visual_pages_per_domain: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    maximum_crawl_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    per_domain_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    crawl_delay_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    overall_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    desktop_viewport: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    mobile_viewport: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    allowed_content_types: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    include_url_patterns: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    exclude_url_patterns: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    timeout_limits: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    artifact_retention_policy: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    workflow_id: Mapped[str | None] = mapped_column(String(300))
    workflow_run_id: Mapped[str | None] = mapped_column(String(100))
    workflow_attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="scan_campaigns")
    targets: Mapped[list[ScanTarget]] = relationship(back_populates="campaign")
    crawl_pages: Mapped[list[CrawlPage]] = relationship(back_populates="campaign")
    page_scans: Mapped[list[PageScan]] = relationship(back_populates="campaign")
    failures: Mapped[list[ScanFailure]] = relationship(back_populates="campaign")


class ScanTarget(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Validated seed URL belonging to a draft scan campaign."""

    __tablename__ = "scan_targets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'completed', 'failed')",
            name="status_allowed",
        ),
        Index("ix_scan_targets_campaign_id_status", "campaign_id", "status"),
        UniqueConstraint("campaign_id", "normalized_url"),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(2_048), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(2_048), nullable=False)
    source_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    campaign: Mapped[ScanCampaign] = relationship(back_populates="targets")
    crawl_pages: Mapped[list[CrawlPage]] = relationship(back_populates="target")
    failures: Mapped[list[ScanFailure]] = relationship(back_populates="target")


class CrawlPage(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Discovered page metadata; HTML bodies remain in private object storage."""

    __tablename__ = "crawl_pages"
    __table_args__ = (
        CheckConstraint("depth BETWEEN 0 AND 20", name="depth_valid"),
        CheckConstraint(
            "status IN ('discovered', 'blocked', 'fetching', 'fetched', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599", name="http_status_valid"
        ),
        Index("ix_crawl_pages_campaign_id_status", "campaign_id", "status"),
        Index("ix_crawl_pages_target_id_depth", "target_id", "depth"),
        UniqueConstraint("campaign_id", "normalized_url"),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    target_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_targets.id", ondelete="CASCADE"), nullable=False
    )
    parent_page_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("crawl_pages.id", ondelete="SET NULL")
    )
    url: Mapped[str] = mapped_column(String(2_048), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(2_048), nullable=False)
    source_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="discovered")
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean)
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(255))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    response_artifact_key: Mapped[str | None] = mapped_column(String(1_024))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[ScanCampaign] = relationship(back_populates="crawl_pages")
    target: Mapped[ScanTarget] = relationship(back_populates="crawl_pages")
    page_scans: Mapped[list[PageScan]] = relationship(back_populates="crawl_page")
    failures: Mapped[list[ScanFailure]] = relationship(back_populates="crawl_page")


class PageScan(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Rendered viewport scan metadata referencing private artifacts by object key."""

    __tablename__ = "page_scans"
    __table_args__ = (
        CheckConstraint("viewport IN ('desktop', 'mobile')", name="viewport_allowed"),
        CheckConstraint(
            "status IN ('pending', 'rendering', 'succeeded', 'failed', 'cancelled')",
            name="status_allowed",
        ),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        Index("ix_page_scans_campaign_id_status", "campaign_id", "status"),
        UniqueConstraint("crawl_page_id", "viewport", "attempt"),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    crawl_page_id: Mapped[UUID] = mapped_column(
        ForeignKey("crawl_pages.id", ondelete="CASCADE"), nullable=False
    )
    viewport: Mapped[str] = mapped_column(String(16), nullable=False)
    viewport_width: Mapped[int] = mapped_column(Integer, nullable=False)
    viewport_height: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    screenshot_artifact_key: Mapped[str | None] = mapped_column(String(1_024))
    rendered_html_artifact_key: Mapped[str | None] = mapped_column(String(1_024))
    analysis_artifact_key: Mapped[str | None] = mapped_column(String(1_024))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[ScanCampaign] = relationship(back_populates="page_scans")
    crawl_page: Mapped[CrawlPage] = relationship(back_populates="page_scans")
    failures: Mapped[list[ScanFailure]] = relationship(back_populates="page_scan")


class ScanFailure(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Sanitized, retry-addressable scan failure projection."""

    __tablename__ = "scan_failures"
    __table_args__ = (
        CheckConstraint(
            "stage IN ('control', 'crawl', 'browser', 'analysis', 'embedding')",
            name="stage_allowed",
        ),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        Index("ix_scan_failures_campaign_id_resolved_at", "campaign_id", "resolved_at"),
        Index("ix_scan_failures_campaign_id_retryable", "campaign_id", "retryable"),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    target_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("scan_targets.id", ondelete="SET NULL")
    )
    crawl_page_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("crawl_pages.id", ondelete="SET NULL")
    )
    page_scan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("page_scans.id", ondelete="SET NULL")
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str] = mapped_column(String(100), nullable=False)
    message: Mapped[str] = mapped_column(String(1_000), nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[ScanCampaign] = relationship(back_populates="failures")
    target: Mapped[ScanTarget | None] = relationship(back_populates="failures")
    crawl_page: Mapped[CrawlPage | None] = relationship(back_populates="failures")
    page_scan: Mapped[PageScan | None] = relationship(back_populates="failures")


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """Append-only security and business decision record."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[UUID | None]
    request_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class JobEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only durable event projection for asynchronous jobs."""

    __tablename__ = "job_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="status_allowed",
        ),
        CheckConstraint("sequence >= 0", name="sequence_non_negative"),
        UniqueConstraint("job_id", "sequence"),
        Index("ix_job_events_project_id_created_at", "project_id", "created_at"),
    )

    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    job_id: Mapped[UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
