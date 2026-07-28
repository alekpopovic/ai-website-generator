"""Add typed immutable scan artifact records.

Revision ID: 20260728_0013
Revises: 20260728_0012
Create Date: 2026-07-28 00:00:07+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0013"
down_revision: str | None = "20260728_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scan_artifacts",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("source_website_id", sa.Uuid(), nullable=False),
        sa.Column("crawl_page_id", sa.Uuid(), nullable=False),
        sa.Column("page_scan_id", sa.Uuid()),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("bucket", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("content_encoding", sa.String(length=32)),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("final_url", sa.String(length=2048), nullable=False),
        sa.Column("scan_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scanner_version", sa.String(length=200), nullable=False),
        sa.Column("viewport", sa.String(length=16)),
        sa.Column("provenance_status", sa.String(length=32), nullable=False),
        sa.Column("access_policy", sa.String(length=32), nullable=False),
        sa.Column("retention_policy", sa.String(length=64), nullable=False),
        sa.Column("retention_status", sa.String(length=32), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True)),
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True)),
        sa.Column("deletion_requested_by_user_id", sa.Uuid()),
        sa.Column("deletion_reason", sa.String(length=500)),
        sa.Column("deletion_workflow_id", sa.String(length=255)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "bucket = 'scan-artifacts'", name=op.f("ck_scan_artifacts_bucket_allowed")
        ),
        sa.CheckConstraint(
            "artifact_type IN ('raw_response_html', 'rendered_html', 'desktop_screenshot', "
            "'mobile_screenshot', 'viewport_screenshot', 'semantic_snapshot', "
            "'extracted_nodes', 'style_summary', 'network_manifest', "
            "'console_diagnostics', 'scan_metadata_manifest')",
            name=op.f("ck_scan_artifacts_artifact_type_allowed"),
        ),
        sa.CheckConstraint(
            "access_policy IN ('restricted_raw', 'project_member', 'safe_screenshot')",
            name=op.f("ck_scan_artifacts_access_policy_allowed"),
        ),
        sa.CheckConstraint(
            "retention_status IN ('active', 'pending_deletion', 'legal_hold', 'expired', "
            "'deleted')",
            name=op.f("ck_scan_artifacts_retention_status_allowed"),
        ),
        sa.CheckConstraint(
            "provenance_status IN ('authorized', 'restricted', 'removal_pending', 'removed')",
            name=op.f("ck_scan_artifacts_provenance_status_allowed"),
        ),
        sa.CheckConstraint(
            "size_bytes >= 0", name=op.f("ck_scan_artifacts_size_bytes_nonnegative")
        ),
        sa.CheckConstraint(
            "viewport IS NULL OR viewport IN ('desktop', 'mobile')",
            name=op.f("ck_scan_artifacts_viewport_allowed"),
        ),
        sa.ForeignKeyConstraint(["campaign_id"], ["scan_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["crawl_page_id"], ["crawl_pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["deletion_requested_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["page_scan_id"], ["page_scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_website_id"], ["scan_targets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_artifacts")),
        sa.UniqueConstraint(
            "bucket", "object_key", name=op.f("uq_scan_artifacts_bucket_object_key")
        ),
    )
    op.create_index(
        "ix_scan_artifacts_campaign_type",
        "scan_artifacts",
        ["campaign_id", "artifact_type"],
    )
    op.create_index("ix_scan_artifacts_crawl_page_id", "scan_artifacts", ["crawl_page_id"])
    op.create_index("ix_scan_artifacts_page_scan_id", "scan_artifacts", ["page_scan_id"])


def downgrade() -> None:
    op.drop_index("ix_scan_artifacts_page_scan_id", table_name="scan_artifacts")
    op.drop_index("ix_scan_artifacts_crawl_page_id", table_name="scan_artifacts")
    op.drop_index("ix_scan_artifacts_campaign_type", table_name="scan_artifacts")
    op.drop_table("scan_artifacts")
