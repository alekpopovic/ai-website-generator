"""Initial PostgreSQL-owned application records."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
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
        CheckConstraint("respect_robots_txt IS TRUE", name="robots_required"),
        CheckConstraint(
            "query_parameter_ordering IN ('preserve', 'sorted')",
            name="query_parameter_ordering_allowed",
        ),
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
    crawler_user_agent: Mapped[str] = mapped_column(
        String(256), nullable=False, default="AIWebsiteGeneratorBot/1.0"
    )
    max_discovered_pages_per_domain: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100
    )
    max_visual_pages_per_domain: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    include_restricted_representatives: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
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
    tracking_query_parameters: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    query_parameter_ordering: Mapped[str] = mapped_column(
        String(16), nullable=False, default="sorted"
    )
    store_raw_html: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
    target_imports: Mapped[list[ScanTargetImport]] = relationship(back_populates="campaign")
    crawl_policy_records: Mapped[list[CrawlPolicyRecord]] = relationship(back_populates="campaign")


class ScanTarget(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Validated seed URL belonging to a draft scan campaign."""

    __tablename__ = "scan_targets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'completed', 'failed')",
            name="status_allowed",
        ),
        Index("ix_scan_targets_campaign_id_status", "campaign_id", "status"),
        Index("ix_scan_targets_campaign_id_source_domain", "campaign_id", "source_domain"),
        UniqueConstraint("campaign_id", "normalized_url"),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    import_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("scan_target_imports.id", ondelete="SET NULL")
    )
    import_row_number: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(String(2_048), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(2_048), nullable=False)
    source_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    import_metadata: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    campaign: Mapped[ScanCampaign] = relationship(back_populates="targets")
    crawl_pages: Mapped[list[CrawlPage]] = relationship(back_populates="target")
    failures: Mapped[list[ScanFailure]] = relationship(back_populates="target")
    crawl_policy_records: Mapped[list[CrawlPolicyRecord]] = relationship(back_populates="target")


class CrawlPolicyRecord(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Durable robots result and effective domain-level policy provenance."""

    __tablename__ = "crawl_policy_records"
    __table_args__ = (
        CheckConstraint(
            "fetch_status IN ('fetched', 'not_found', 'unavailable', 'invalid', "
            "'oversized', 'redirect_limit_exceeded', 'blocked')",
            name="fetch_status_allowed",
        ),
        CheckConstraint("redirect_count BETWEEN 0 AND 20", name="redirect_count_valid"),
        UniqueConstraint("campaign_id", "target_id"),
        Index("ix_crawl_policy_records_campaign_id_source_domain", "campaign_id", "source_domain"),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    target_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_targets.id", ondelete="CASCADE"), nullable=False
    )
    source_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    robots_url: Mapped[str] = mapped_column(String(2_048), nullable=False)
    final_robots_url: Mapped[str] = mapped_column(String(2_048), nullable=False)
    fetch_status: Mapped[str] = mapped_column(String(32), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    crawler_user_agent: Mapped[str] = mapped_column(String(256), nullable=False)
    crawl_delay_seconds: Mapped[float | None] = mapped_column(Float)
    redirect_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sitemap_urls: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    effective_policy: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    campaign: Mapped[ScanCampaign] = relationship(back_populates="crawl_policy_records")
    target: Mapped[ScanTarget] = relationship(back_populates="crawl_policy_records")
    crawl_pages: Mapped[list[CrawlPage]] = relationship(back_populates="crawl_policy_record")


class ScanTargetImport(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Bounded target-import run with durable progress and summary counters."""

    __tablename__ = "scan_target_imports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('validating', 'completed', 'committed', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint("source_type IN ('paste', 'text', 'csv')", name="source_type_allowed"),
        CheckConstraint("total_rows BETWEEN 0 AND 50000", name="total_rows_bounded"),
        CheckConstraint("processed_rows BETWEEN 0 AND 50000", name="processed_rows_bounded"),
        CheckConstraint(
            "accepted_count >= 0 AND duplicate_count >= 0 AND invalid_count >= 0 "
            "AND blocked_count >= 0 AND already_present_count >= 0 AND committed_count >= 0",
            name="counts_non_negative",
        ),
        CheckConstraint("committed_count <= accepted_count", name="committed_not_above_accepted"),
        Index("ix_scan_target_imports_campaign_id_created_at", "campaign_id", "created_at"),
    )

    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    filename: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    authorization_attested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    allow_ip_literals: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="validating")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    already_present_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    committed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[ScanCampaign] = relationship(back_populates="target_imports")
    rows: Mapped[list[ScanTargetImportRow]] = relationship(back_populates="target_import")


class ScanTargetImportRow(UUIDPrimaryKeyMixin, Base):
    """One source row and its deterministic, typed validation outcome."""

    __tablename__ = "scan_target_import_rows"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('accepted', 'duplicate', 'invalid', 'blocked', 'already_present')",
            name="outcome_allowed",
        ),
        CheckConstraint("row_number BETWEEN 1 AND 50000", name="row_number_bounded"),
        UniqueConstraint("import_id", "row_number"),
        Index("ix_scan_target_import_rows_import_id_outcome", "import_id", "outcome"),
    )

    import_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_target_imports.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_value: Mapped[str] = mapped_column(String(2_048), nullable=False)
    normalized_url: Mapped[str | None] = mapped_column(String(2_048))
    source_domain: Mapped[str | None] = mapped_column(String(253))
    row_metadata: Mapped[JsonValue] = mapped_column(
        "metadata", SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    reason_message: Mapped[str | None] = mapped_column(String(500))
    target_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("scan_targets.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    target_import: Mapped[ScanTargetImport] = relationship(back_populates="rows")


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
        CheckConstraint(
            "content_length IS NULL OR content_length >= 0", name="content_length_non_negative"
        ),
        CheckConstraint(
            "fingerprint_version IS NULL OR fingerprint_version >= 1",
            name="fingerprint_version_positive",
        ),
        CheckConstraint(
            "normalized_text_length IS NULL OR normalized_text_length >= 0",
            name="normalized_text_length_non_negative",
        ),
        CheckConstraint(
            "discovery_source IN ("
            "'submitted_root', 'robots_sitemap', 'sitemap', 'html_link', 'canonical')",
            name="discovery_source_allowed",
        ),
        CheckConstraint(
            "page_type IS NULL OR page_type IN ("
            "'homepage', 'about', 'services', 'product', 'features', 'pricing', 'contact', "
            "'documentation', 'blog-index', 'article', 'case-study', 'careers', 'legal', "
            "'authentication', 'unknown')",
            name="page_type_allowed",
        ),
        CheckConstraint(
            "manual_selection IN ('automatic', 'include', 'exclude')",
            name="manual_selection_allowed",
        ),
        CheckConstraint(
            "representative_rank IS NULL OR representative_rank >= 1",
            name="representative_rank_positive",
        ),
        Index("ix_crawl_pages_campaign_id_status", "campaign_id", "status"),
        Index("ix_crawl_pages_target_id_depth", "target_id", "depth"),
        Index(
            "ix_crawl_pages_campaign_content_fingerprint",
            "campaign_id",
            "normalized_content_sha256",
        ),
        Index("ix_crawl_pages_campaign_semantic_simhash", "campaign_id", "semantic_simhash"),
        Index(
            "ix_crawl_pages_campaign_template_fingerprint",
            "campaign_id",
            "dom_template_sha256",
        ),
        Index("ix_crawl_pages_exact_duplicate_of_id", "exact_duplicate_of_id"),
        Index("ix_crawl_pages_near_duplicate_of_id", "near_duplicate_of_id"),
        Index("ix_crawl_pages_template_representative_id", "template_representative_id"),
        Index("ix_crawl_pages_campaign_page_type", "campaign_id", "page_type"),
        Index(
            "ix_crawl_pages_campaign_representative",
            "campaign_id",
            "representative_selected",
            "representative_rank",
        ),
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
    crawl_policy_record_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("crawl_policy_records.id", ondelete="SET NULL")
    )
    url: Mapped[str] = mapped_column(String(2_048), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(2_048), nullable=False)
    final_url: Mapped[str | None] = mapped_column(String(2_048))
    declared_canonical_url: Mapped[str | None] = mapped_column(String(2_048))
    source_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="discovered")
    robots_allowed: Mapped[bool | None] = mapped_column(Boolean)
    crawl_decision_code: Mapped[str | None] = mapped_column(String(64))
    crawl_policy_provenance: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(255))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(String(500))
    meta_description: Mapped[str | None] = mapped_column(String(1_000))
    language: Mapped[str | None] = mapped_column(String(35))
    hreflang_links: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    last_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_length: Mapped[int | None] = mapped_column(Integer)
    discovery_source: Mapped[str] = mapped_column(String(32), nullable=False, default="html_link")
    parent_url: Mapped[str | None] = mapped_column(String(2_048))
    response_artifact_key: Mapped[str | None] = mapped_column(String(1_024))
    fingerprint_algorithm: Mapped[str | None] = mapped_column(String(64))
    fingerprint_version: Mapped[int | None] = mapped_column(Integer)
    normalized_url_sha256: Mapped[str | None] = mapped_column(String(64))
    visible_text_sha256: Mapped[str | None] = mapped_column(String(64))
    dom_structure_sha256: Mapped[str | None] = mapped_column(String(64))
    heading_sequence_sha256: Mapped[str | None] = mapped_column(String(64))
    link_structure_sha256: Mapped[str | None] = mapped_column(String(64))
    semantic_simhash: Mapped[str | None] = mapped_column(String(16))
    dom_template_sha256: Mapped[str | None] = mapped_column(String(64))
    normalized_content_sha256: Mapped[str | None] = mapped_column(String(64))
    normalized_text_length: Mapped[int | None] = mapped_column(Integer)
    exact_duplicate_of_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("crawl_pages.id", ondelete="SET NULL")
    )
    near_duplicate_of_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("crawl_pages.id", ondelete="SET NULL")
    )
    template_representative_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("crawl_pages.id", ondelete="SET NULL")
    )
    exact_group_key: Mapped[str | None] = mapped_column(String(64))
    near_group_key: Mapped[str | None] = mapped_column(String(64))
    template_group_key: Mapped[str | None] = mapped_column(String(64))
    fingerprinted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    page_type: Mapped[str | None] = mapped_column(String(32))
    page_type_score: Mapped[float | None] = mapped_column(Float)
    classification_features: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    classification_explanation: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    classifier: Mapped[str | None] = mapped_column(String(64))
    classifier_version: Mapped[int | None] = mapped_column(Integer)
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    representative_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    representative_rank: Mapped[int | None] = mapped_column(Integer)
    representative_score: Mapped[float | None] = mapped_column(Float)
    selection_explanation: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    selector: Mapped[str | None] = mapped_column(String(64))
    selector_version: Mapped[int | None] = mapped_column(Integer)
    manual_selection: Mapped[str] = mapped_column(String(16), nullable=False, default="automatic")
    manual_selection_reason: Mapped[str | None] = mapped_column(String(500))
    manual_selected_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    manual_selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[ScanCampaign] = relationship(back_populates="crawl_pages")
    target: Mapped[ScanTarget] = relationship(back_populates="crawl_pages")
    page_scans: Mapped[list[PageScan]] = relationship(back_populates="crawl_page")
    failures: Mapped[list[ScanFailure]] = relationship(back_populates="crawl_page")
    crawl_policy_record: Mapped[CrawlPolicyRecord | None] = relationship(
        back_populates="crawl_pages"
    )


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
        CheckConstraint(
            "capture_schema_version IS NULL OR capture_schema_version >= 1",
            name="capture_schema_version_positive",
        ),
        CheckConstraint(
            "document_width IS NULL OR document_width >= 1", name="document_width_positive"
        ),
        CheckConstraint(
            "document_height IS NULL OR document_height >= 1", name="document_height_positive"
        ),
        CheckConstraint(
            "extracted_node_count IS NULL OR extracted_node_count >= 0",
            name="extracted_node_count_nonnegative",
        ),
        CheckConstraint(
            "extraction_payload_bytes IS NULL OR extraction_payload_bytes >= 0",
            name="extraction_payload_bytes_nonnegative",
        ),
        Index("ix_page_scans_campaign_id_status", "campaign_id", "status"),
        Index("ix_page_scans_configuration_hash", "configuration_hash"),
        UniqueConstraint("crawl_page_id", "viewport", "attempt"),
        UniqueConstraint("crawl_page_id", "viewport", "configuration_hash"),
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
    viewport_screenshot_artifact_key: Mapped[str | None] = mapped_column(String(1_024))
    semantic_snapshot_artifact_key: Mapped[str | None] = mapped_column(String(1_024))
    configuration_hash: Mapped[str | None] = mapped_column(String(64))
    capture_schema_version: Mapped[int | None] = mapped_column(Integer)
    browser_version: Mapped[str | None] = mapped_column(String(64))
    final_url: Mapped[str | None] = mapped_column(String(2_048))
    artifact_checksums: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    response_metadata: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    page_title: Mapped[str | None] = mapped_column(String(500))
    meta_description: Mapped[str | None] = mapped_column(String(1_000))
    canonical_url: Mapped[str | None] = mapped_column(String(2_048))
    language: Mapped[str | None] = mapped_column(String(35))
    visible_text_summary: Mapped[str | None] = mapped_column(String(4_000))
    extractor_version: Mapped[str | None] = mapped_column(String(64))
    extracted_node_count: Mapped[int | None] = mapped_column(Integer)
    extraction_payload_bytes: Mapped[int | None] = mapped_column(Integer)
    extraction_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    semantic_snapshot_summary: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    console_errors: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    page_errors: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    failed_requests: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    external_host_manifest: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    document_width: Mapped[int | None] = mapped_column(Integer)
    document_height: Mapped[int | None] = mapped_column(Integer)
    screenshot_width: Mapped[int | None] = mapped_column(Integer)
    screenshot_height: Mapped[int | None] = mapped_column(Integer)
    full_page_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[ScanCampaign] = relationship(back_populates="page_scans")
    crawl_page: Mapped[CrawlPage] = relationship(back_populates="page_scans")
    failures: Mapped[list[ScanFailure]] = relationship(back_populates="page_scan")


class ScanArtifact(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Typed immutable scan object with ownership, provenance, and retention state."""

    __tablename__ = "scan_artifacts"
    __table_args__ = (
        CheckConstraint("bucket = 'scan-artifacts'", name="bucket_allowed"),
        CheckConstraint(
            "artifact_type IN ('raw_response_html', 'rendered_html', "
            "'desktop_screenshot', 'mobile_screenshot', 'viewport_screenshot', "
            "'semantic_snapshot', 'extracted_nodes', 'style_summary', "
            "'network_manifest', 'console_diagnostics', 'scan_metadata_manifest')",
            name="artifact_type_allowed",
        ),
        CheckConstraint(
            "access_policy IN ('restricted_raw', 'project_member', 'safe_screenshot')",
            name="access_policy_allowed",
        ),
        CheckConstraint(
            "retention_status IN ('active', 'pending_deletion', 'legal_hold', 'expired', "
            "'deleted')",
            name="retention_status_allowed",
        ),
        CheckConstraint(
            "provenance_status IN ('authorized', 'restricted', 'removal_pending', 'removed')",
            name="provenance_status_allowed",
        ),
        CheckConstraint("size_bytes >= 0", name="size_bytes_nonnegative"),
        CheckConstraint(
            "viewport IS NULL OR viewport IN ('desktop', 'mobile')", name="viewport_allowed"
        ),
        Index("ix_scan_artifacts_campaign_type", "campaign_id", "artifact_type"),
        Index("ix_scan_artifacts_crawl_page_id", "crawl_page_id"),
        Index("ix_scan_artifacts_page_scan_id", "page_scan_id"),
        UniqueConstraint("bucket", "object_key"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    source_website_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_targets.id", ondelete="CASCADE"), nullable=False
    )
    crawl_page_id: Mapped[UUID] = mapped_column(
        ForeignKey("crawl_pages.id", ondelete="CASCADE"), nullable=False
    )
    page_scan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("page_scans.id", ondelete="CASCADE")
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    bucket: Mapped[str] = mapped_column(String(64), nullable=False, default="scan-artifacts")
    object_key: Mapped[str] = mapped_column(String(1_024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    content_encoding: Mapped[str | None] = mapped_column(String(32))
    source_url: Mapped[str] = mapped_column(String(2_048), nullable=False)
    final_url: Mapped[str] = mapped_column(String(2_048), nullable=False)
    scan_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scanner_version: Mapped[str] = mapped_column(String(200), nullable=False)
    viewport: Mapped[str | None] = mapped_column(String(16))
    provenance_status: Mapped[str] = mapped_column(String(32), nullable=False)
    access_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    retention_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    retention_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_requested_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    deletion_reason: Mapped[str | None] = mapped_column(String(500))
    deletion_workflow_id: Mapped[str | None] = mapped_column(String(255))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only record of one structured analyzer invocation."""

    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint("output_kind IN ('page', 'website')", name="output_kind_allowed"),
        CheckConstraint("status IN ('succeeded', 'failed', 'cancelled')", name="status_allowed"),
        CheckConstraint(
            "provenance_state IN ('authorized', 'restricted', 'removal_pending', 'removed')",
            name="provenance_state_allowed",
        ),
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
        CheckConstraint("attempts >= 1", name="attempts_positive"),
        CheckConstraint("latency_ms >= 0", name="latency_nonnegative"),
        Index("ix_analysis_runs_project_created", "project_id", "created_at"),
        Index("ix_analysis_runs_page_created", "source_page_id", "created_at"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    source_website_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_targets.id", ondelete="CASCADE"), nullable=False
    )
    source_page_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("crawl_pages.id", ondelete="CASCADE")
    )
    output_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="succeeded")
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(100), nullable=False)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    model_digest: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    used_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provenance_state: Mapped[str] = mapped_column(String(32), nullable=False, default="authorized")
    result_sha256: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(100))


class PageProfile(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Historical normalized page profile with exactly one current row per source page."""

    __tablename__ = "page_profiles"
    __table_args__ = (
        CheckConstraint(
            "approval_state IN ('needs_review', 'approved', 'rejected')",
            name="approval_state_allowed",
        ),
        CheckConstraint(
            "provenance_state IN ('authorized', 'restricted', 'removal_pending', 'removed')",
            name="provenance_state_allowed",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_valid"),
        Index("ix_page_profiles_project_current", "project_id", "is_current"),
        Index("ix_page_profiles_page_type", "project_id", "page_type"),
        Index(
            "uq_page_profiles_current_source_page",
            "source_page_id",
            unique=True,
            postgresql_where=text("is_current IS TRUE"),
        ),
        UniqueConstraint("analysis_run_id"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    source_website_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_targets.id", ondelete="CASCADE"), nullable=False
    )
    source_page_id: Mapped[UUID] = mapped_column(
        ForeignKey("crawl_pages.id", ondelete="CASCADE"), nullable=False
    )
    analysis_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    profile_json: Mapped[JsonValue] = mapped_column(SafeJSONB, nullable=False)
    page_type: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(35), nullable=False)
    style_tags: Mapped[JsonValue] = mapped_column(SafeJSONB, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(100), nullable=False)
    model_digest: Mapped[str] = mapped_column(String(200), nullable=False)
    approval_state: Mapped[str] = mapped_column(String(32), nullable=False, default="needs_review")
    provenance_state: Mapped[str] = mapped_column(String(32), nullable=False, default="authorized")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(String(500))


class WebsiteProfile(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Historical aggregate website profile."""

    __tablename__ = "website_profiles"
    __table_args__ = (
        CheckConstraint(
            "approval_state IN ('needs_review', 'approved', 'rejected')",
            name="approval_state_allowed",
        ),
        CheckConstraint(
            "provenance_state IN ('authorized', 'restricted', 'removal_pending', 'removed')",
            name="provenance_state_allowed",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_valid"),
        Index("ix_website_profiles_project_current", "project_id", "is_current"),
        Index(
            "uq_website_profiles_current_source_website",
            "source_website_id",
            unique=True,
            postgresql_where=text("is_current IS TRUE"),
        ),
        UniqueConstraint("analysis_run_id"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    source_website_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_targets.id", ondelete="CASCADE"), nullable=False
    )
    analysis_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    profile_json: Mapped[JsonValue] = mapped_column(SafeJSONB, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(35), nullable=False)
    style_tags: Mapped[JsonValue] = mapped_column(SafeJSONB, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(100), nullable=False)
    model_digest: Mapped[str] = mapped_column(String(200), nullable=False)
    approval_state: Mapped[str] = mapped_column(String(32), nullable=False, default="needs_review")
    provenance_state: Mapped[str] = mapped_column(String(32), nullable=False, default="authorized")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(String(500))


class SectionPattern(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Independent abstract section suitable for curated vector retrieval."""

    __tablename__ = "section_patterns"
    __table_args__ = (
        CheckConstraint(
            "approval_state IN ('needs_review', 'approved', 'rejected')",
            name="approval_state_allowed",
        ),
        CheckConstraint(
            "provenance_state IN ('authorized', 'restricted', 'removal_pending', 'removed')",
            name="provenance_state_allowed",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_valid"),
        CheckConstraint("section_order BETWEEN 0 AND 255", name="section_order_valid"),
        Index("ix_section_patterns_project_type", "project_id", "section_type"),
        Index("ix_section_patterns_hash", "project_id", "pattern_hash"),
        Index("ix_section_patterns_page_profile", "page_profile_id", "section_order"),
        UniqueConstraint("page_profile_id", "section_order"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_campaigns.id", ondelete="CASCADE"), nullable=False
    )
    source_website_id: Mapped[UUID] = mapped_column(
        ForeignKey("scan_targets.id", ondelete="CASCADE"), nullable=False
    )
    source_page_id: Mapped[UUID] = mapped_column(
        ForeignKey("crawl_pages.id", ondelete="CASCADE"), nullable=False
    )
    analysis_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    page_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("page_profiles.id", ondelete="CASCADE"), nullable=False
    )
    duplicate_of_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("section_patterns.id", ondelete="SET NULL")
    )
    pattern_json: Mapped[JsonValue] = mapped_column(SafeJSONB, nullable=False)
    section_order: Mapped[int] = mapped_column(Integer, nullable=False)
    section_type: Mapped[str] = mapped_column(String(32), nullable=False)
    layout: Mapped[str] = mapped_column(String(32), nullable=False)
    style_tags: Mapped[JsonValue] = mapped_column(SafeJSONB, nullable=False, default=list)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(35), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    analyzer_version: Mapped[str] = mapped_column(String(100), nullable=False)
    model_digest: Mapped[str] = mapped_column(String(200), nullable=False)
    approval_state: Mapped[str] = mapped_column(String(32), nullable=False, default="needs_review")
    provenance_state: Mapped[str] = mapped_column(String(32), nullable=False, default="authorized")
    retrieval_document: Mapped[str] = mapped_column(String(4_000), nullable=False)
    pattern_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieval_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieval_removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legally_suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(String(500))


class EmbeddingRun(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Durable incremental index or full-reindex progress record."""

    __tablename__ = "embedding_runs"
    __table_args__ = (
        CheckConstraint("kind IN ('incremental', 'reindex')", name="kind_allowed"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="status_allowed",
        ),
        CheckConstraint("batch_size BETWEEN 1 AND 256", name="batch_size_valid"),
        CheckConstraint(
            "total_patterns >= 0 AND processed_patterns >= 0 AND indexed_patterns >= 0 "
            "AND deleted_patterns >= 0 AND failed_patterns >= 0",
            name="counts_nonnegative",
        ),
        Index("ix_embedding_runs_project_created", "project_id", "created_at"),
        Index("ix_embedding_runs_project_status", "project_id", "status"),
        UniqueConstraint("project_id", "idempotency_key"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=64)
    promote_alias: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    collection_alias: Mapped[str] = mapped_column(String(64), nullable=False)
    physical_collection: Mapped[str | None] = mapped_column(String(240))
    embedding_provider: Mapped[str | None] = mapped_column(String(32))
    embedding_model: Mapped[str | None] = mapped_column(String(200))
    embedding_model_digest: Mapped[str | None] = mapped_column(String(128))
    serialization_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    vector_name: Mapped[str] = mapped_column(String(64), nullable=False, default="design-pattern")
    dimensions: Mapped[int | None] = mapped_column(Integer)
    total_patterns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_patterns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_patterns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_patterns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_patterns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    workflow_id: Mapped[str | None] = mapped_column(String(255))
    workflow_run_id: Mapped[str | None] = mapped_column(String(255))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alias_switched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SectionPatternEmbedding(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Per-physical-collection index state for one authoritative section pattern."""

    __tablename__ = "section_pattern_embeddings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'indexing', 'indexed', 'deleting', 'deleted', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        Index("ix_section_pattern_embeddings_run_status", "embedding_run_id", "status"),
        Index("ix_section_pattern_embeddings_pattern", "section_pattern_id", "status"),
        Index("ix_section_pattern_embeddings_collection", "physical_collection", "status"),
        UniqueConstraint("section_pattern_id", "physical_collection"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    section_pattern_id: Mapped[UUID] = mapped_column(
        ForeignKey("section_patterns.id", ondelete="CASCADE"), nullable=False
    )
    embedding_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("embedding_runs.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[UUID | None]
    dataset_version_id: Mapped[UUID | None]
    physical_collection: Mapped[str] = mapped_column(String(240), nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    embedding_model_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    serialization_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_name: Mapped[str] = mapped_column(String(64), nullable=False)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmbeddingIndexFailure(UUIDPrimaryKeyMixin, Base):
    """Append-only sanitized indexing failure history."""

    __tablename__ = "embedding_index_failures"
    __table_args__ = (
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        Index("ix_embedding_index_failures_run_created", "embedding_run_id", "created_at"),
    )

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    embedding_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("embedding_runs.id", ondelete="CASCADE"), nullable=False
    )
    section_pattern_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("section_patterns.id", ondelete="SET NULL")
    )
    error_code: Mapped[str] = mapped_column(String(100), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


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
        UniqueConstraint("campaign_id", "failure_key"),
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
    failure_key: Mapped[str | None] = mapped_column(String(64))
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
