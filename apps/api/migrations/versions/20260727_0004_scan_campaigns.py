"""Add scan campaign control-plane persistence.

Revision ID: 20260727_0004
Revises: 20260727_0003
Create Date: 2026-07-27 00:00:03+00:00
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260727_0004"
down_revision: str | None = "20260727_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _identity_columns() -> tuple[sa.Column[Any], ...]:
    return (
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )


def upgrade() -> None:
    """Create scan configuration, discovered-page, rendered-scan, and failure tables."""
    op.create_table(
        "scan_campaigns",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("authorization_attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("respect_robots_txt", sa.Boolean(), nullable=False),
        sa.Column("max_discovered_pages_per_domain", sa.Integer(), nullable=False),
        sa.Column("max_visual_pages_per_domain", sa.Integer(), nullable=False),
        sa.Column("maximum_crawl_depth", sa.Integer(), nullable=False),
        sa.Column("per_domain_concurrency", sa.Integer(), nullable=False),
        sa.Column("crawl_delay_seconds", sa.Float(), nullable=False),
        sa.Column("overall_concurrency", sa.Integer(), nullable=False),
        sa.Column(
            "desktop_viewport",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "mobile_viewport",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "allowed_content_types",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "include_url_patterns",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "exclude_url_patterns",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "timeout_limits",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "artifact_retention_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("workflow_id", sa.String(length=300)),
        sa.Column("workflow_run_id", sa.String(length=100)),
        sa.Column("workflow_attempt", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *_identity_columns(),
        sa.CheckConstraint(
            "status IN ('draft', 'queued', 'running', 'pausing', 'paused', "
            "'cancelling', 'cancelled', 'succeeded', 'partially_succeeded', 'failed')",
            name="ck_scan_campaigns_status_allowed",
        ),
        sa.CheckConstraint(
            "max_discovered_pages_per_domain BETWEEN 1 AND 10000",
            name="ck_scan_campaigns_max_discovered_pages_valid",
        ),
        sa.CheckConstraint(
            "max_visual_pages_per_domain BETWEEN 0 AND 1000",
            name="ck_scan_campaigns_max_visual_pages_valid",
        ),
        sa.CheckConstraint(
            "maximum_crawl_depth BETWEEN 0 AND 20",
            name="ck_scan_campaigns_crawl_depth_valid",
        ),
        sa.CheckConstraint(
            "per_domain_concurrency BETWEEN 1 AND 32",
            name="ck_scan_campaigns_per_domain_concurrency_valid",
        ),
        sa.CheckConstraint(
            "crawl_delay_seconds BETWEEN 0 AND 60",
            name="ck_scan_campaigns_crawl_delay_valid",
        ),
        sa.CheckConstraint(
            "overall_concurrency BETWEEN 1 AND 128",
            name="ck_scan_campaigns_overall_concurrency_valid",
        ),
        sa.CheckConstraint(
            "workflow_attempt >= 0",
            name="ck_scan_campaigns_workflow_attempt_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_scan_campaigns_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scan_campaigns"),
        sa.UniqueConstraint("project_id", "name", name="uq_scan_campaigns_project_id_name"),
    )
    op.create_index(
        "ix_scan_campaigns_project_id_updated_at",
        "scan_campaigns",
        ["project_id", "updated_at"],
    )
    op.create_index(
        "ix_scan_campaigns_project_id_status",
        "scan_campaigns",
        ["project_id", "status"],
    )

    op.create_table(
        "scan_targets",
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("normalized_url", sa.String(length=2048), nullable=False),
        sa.Column("source_domain", sa.String(length=253), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        *_identity_columns(),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'completed', 'failed')",
            name="ck_scan_targets_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["scan_campaigns.id"],
            name="fk_scan_targets_campaign_id_scan_campaigns",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scan_targets"),
        sa.UniqueConstraint(
            "campaign_id", "normalized_url", name="uq_scan_targets_campaign_id_normalized_url"
        ),
    )
    op.create_index(
        "ix_scan_targets_campaign_id_status",
        "scan_targets",
        ["campaign_id", "status"],
    )

    op.create_table(
        "crawl_pages",
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("parent_page_id", sa.Uuid()),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("normalized_url", sa.String(length=2048), nullable=False),
        sa.Column("source_domain", sa.String(length=253), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("robots_allowed", sa.Boolean()),
        sa.Column("http_status", sa.Integer()),
        sa.Column("content_type", sa.String(length=255)),
        sa.Column("content_sha256", sa.String(length=64)),
        sa.Column("response_artifact_key", sa.String(length=1024)),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        *_identity_columns(),
        sa.CheckConstraint("depth BETWEEN 0 AND 20", name="ck_crawl_pages_depth_valid"),
        sa.CheckConstraint(
            "status IN ('discovered', 'blocked', 'fetching', 'fetched', 'failed')",
            name="ck_crawl_pages_status_allowed",
        ),
        sa.CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599",
            name="ck_crawl_pages_http_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["scan_campaigns.id"],
            name="fk_crawl_pages_campaign_id_scan_campaigns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["scan_targets.id"],
            name="fk_crawl_pages_target_id_scan_targets",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_page_id"],
            ["crawl_pages.id"],
            name="fk_crawl_pages_parent_page_id_crawl_pages",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_crawl_pages"),
        sa.UniqueConstraint(
            "campaign_id", "normalized_url", name="uq_crawl_pages_campaign_id_normalized_url"
        ),
    )
    op.create_index("ix_crawl_pages_campaign_id_status", "crawl_pages", ["campaign_id", "status"])
    op.create_index("ix_crawl_pages_target_id_depth", "crawl_pages", ["target_id", "depth"])

    op.create_table(
        "page_scans",
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("crawl_page_id", sa.Uuid(), nullable=False),
        sa.Column("viewport", sa.String(length=16), nullable=False),
        sa.Column("viewport_width", sa.Integer(), nullable=False),
        sa.Column("viewport_height", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("screenshot_artifact_key", sa.String(length=1024)),
        sa.Column("rendered_html_artifact_key", sa.String(length=1024)),
        sa.Column("analysis_artifact_key", sa.String(length=1024)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        *_identity_columns(),
        sa.CheckConstraint(
            "viewport IN ('desktop', 'mobile')", name="ck_page_scans_viewport_allowed"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'rendering', 'succeeded', 'failed', 'cancelled')",
            name="ck_page_scans_status_allowed",
        ),
        sa.CheckConstraint("attempt >= 1", name="ck_page_scans_attempt_positive"),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["scan_campaigns.id"],
            name="fk_page_scans_campaign_id_scan_campaigns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["crawl_page_id"],
            ["crawl_pages.id"],
            name="fk_page_scans_crawl_page_id_crawl_pages",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_page_scans"),
        sa.UniqueConstraint(
            "crawl_page_id",
            "viewport",
            "attempt",
            name="uq_page_scans_crawl_page_id_viewport_attempt",
        ),
    )
    op.create_index("ix_page_scans_campaign_id_status", "page_scans", ["campaign_id", "status"])

    op.create_table(
        "scan_failures",
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid()),
        sa.Column("crawl_page_id", sa.Uuid()),
        sa.Column("page_scan_id", sa.Uuid()),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=False),
        sa.Column("message", sa.String(length=1000), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        *_identity_columns(),
        sa.CheckConstraint(
            "stage IN ('control', 'crawl', 'browser', 'analysis', 'embedding')",
            name="ck_scan_failures_stage_allowed",
        ),
        sa.CheckConstraint("attempt >= 1", name="ck_scan_failures_attempt_positive"),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["scan_campaigns.id"],
            name="fk_scan_failures_campaign_id_scan_campaigns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["scan_targets.id"],
            name="fk_scan_failures_target_id_scan_targets",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["crawl_page_id"],
            ["crawl_pages.id"],
            name="fk_scan_failures_crawl_page_id_crawl_pages",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["page_scan_id"],
            ["page_scans.id"],
            name="fk_scan_failures_page_scan_id_page_scans",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scan_failures"),
    )
    op.create_index(
        "ix_scan_failures_campaign_id_resolved_at",
        "scan_failures",
        ["campaign_id", "resolved_at"],
    )
    op.create_index(
        "ix_scan_failures_campaign_id_retryable",
        "scan_failures",
        ["campaign_id", "retryable"],
    )


def downgrade() -> None:
    """Remove scan campaign persistence in dependency order."""
    op.drop_index("ix_scan_failures_campaign_id_retryable", table_name="scan_failures")
    op.drop_index("ix_scan_failures_campaign_id_resolved_at", table_name="scan_failures")
    op.drop_table("scan_failures")
    op.drop_index("ix_page_scans_campaign_id_status", table_name="page_scans")
    op.drop_table("page_scans")
    op.drop_index("ix_crawl_pages_target_id_depth", table_name="crawl_pages")
    op.drop_index("ix_crawl_pages_campaign_id_status", table_name="crawl_pages")
    op.drop_table("crawl_pages")
    op.drop_index("ix_scan_targets_campaign_id_status", table_name="scan_targets")
    op.drop_table("scan_targets")
    op.drop_index("ix_scan_campaigns_project_id_status", table_name="scan_campaigns")
    op.drop_index("ix_scan_campaigns_project_id_updated_at", table_name="scan_campaigns")
    op.drop_table("scan_campaigns")
