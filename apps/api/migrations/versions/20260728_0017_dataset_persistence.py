"""Add governed datasets, immutable versions, items, and quality reports.

Revision ID: 20260728_0017
Revises: 20260728_0016
Create Date: 2026-07-28 00:00:11+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0017"
down_revision: str | None = "20260728_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2_000)),
        sa.Column("purpose", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_campaign_filters", postgresql.JSONB(), nullable=False),
        sa.Column("category_filters", postgresql.JSONB(), nullable=False),
        sa.Column("language_filters", postgresql.JSONB(), nullable=False),
        sa.Column("item_types", postgresql.JSONB(), nullable=False),
        sa.Column("minimum_confidence", sa.Float(), nullable=False),
        sa.Column("require_approved", sa.Boolean(), nullable=False),
        sa.Column("provenance_requirements", postgresql.JSONB(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'archived')", name=op.f("ck_datasets_status_allowed")
        ),
        sa.CheckConstraint(
            "minimum_confidence BETWEEN 0 AND 1", name=op.f("ck_datasets_confidence_valid")
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_datasets")),
        sa.UniqueConstraint("project_id", "name", name=op.f("uq_datasets_project_id_name")),
    )
    op.create_index("ix_datasets_project_updated", "datasets", ["project_id", "updated_at"])
    op.create_table(
        "dataset_versions",
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("selection_config", postgresql.JSONB(), nullable=False),
        sa.Column("selection_manifest", postgresql.JSONB(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64)),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("embedding_version", sa.String(240)),
        sa.Column("analyzer_versions", postgresql.JSONB(), nullable=False),
        sa.Column("statistics", postgresql.JSONB(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid()),
        sa.Column("sealed_by_user_id", sa.Uuid()),
        sa.Column("sealed_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'sealed')", name=op.f("ck_dataset_versions_status_allowed")
        ),
        sa.CheckConstraint(
            "version_number >= 1", name=op.f("ck_dataset_versions_version_number_positive")
        ),
        sa.CheckConstraint(
            "schema_version >= 1", name=op.f("ck_dataset_versions_schema_version_positive")
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sealed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_versions")),
        sa.UniqueConstraint(
            "dataset_id",
            "version_number",
            name=op.f("uq_dataset_versions_dataset_id_version_number"),
        ),
    )
    op.create_index(
        "ix_dataset_versions_dataset_created", "dataset_versions", ["dataset_id", "created_at"]
    )
    op.create_table(
        "dataset_items",
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("item_type", sa.String(32), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("source_campaign_id", sa.Uuid(), nullable=False),
        sa.Column("source_website_id", sa.Uuid(), nullable=False),
        sa.Column("source_page_id", sa.Uuid()),
        sa.Column("source_domain", sa.String(253), nullable=False),
        sa.Column("split", sa.String(16), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("language", sa.String(35), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("analyzer_version", sa.String(100), nullable=False),
        sa.Column("content_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("source_reference", postgresql.JSONB(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("availability_status", sa.String(16), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "item_type IN ('section_pattern', 'full_site_spec')",
            name=op.f("ck_dataset_items_item_type_allowed"),
        ),
        sa.CheckConstraint(
            "split IN ('train', 'validation', 'test')", name=op.f("ck_dataset_items_split_allowed")
        ),
        sa.CheckConstraint(
            "availability_status IN ('active', 'removed', 'suppressed')",
            name=op.f("ck_dataset_items_availability_status_allowed"),
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1", name=op.f("ck_dataset_items_confidence_valid")
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["source_campaign_id"], ["scan_campaigns.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_website_id"], ["scan_targets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_page_id"], ["crawl_pages.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_items")),
        sa.UniqueConstraint(
            "dataset_version_id",
            "item_type",
            "source_record_id",
            name=op.f("uq_dataset_items_dataset_version_id_item_type_source_record_id"),
        ),
    )
    op.create_index(
        "ix_dataset_items_version_split", "dataset_items", ["dataset_version_id", "split"]
    )
    op.create_index(
        "ix_dataset_items_version_domain", "dataset_items", ["dataset_version_id", "source_domain"]
    )
    op.create_table(
        "dataset_quality_reports",
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("statistics", postgresql.JSONB(), nullable=False),
        sa.Column("findings", postgresql.JSONB(), nullable=False),
        sa.Column("report_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('passed', 'failed')", name=op.f("ck_dataset_quality_reports_status_allowed")
        ),
        sa.CheckConstraint(
            "item_count >= 0", name=op.f("ck_dataset_quality_reports_item_count_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_quality_reports")),
    )
    op.create_index(
        "ix_dataset_quality_reports_version_created",
        "dataset_quality_reports",
        ["dataset_version_id", "created_at"],
    )
    op.execute(
        """
        CREATE FUNCTION prevent_sealed_dataset_version_mutation() RETURNS trigger AS $$
        BEGIN
          IF OLD.status = 'sealed' THEN
            RAISE EXCEPTION 'sealed dataset versions are immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER dataset_versions_sealed_immutable
        BEFORE UPDATE OR DELETE ON dataset_versions
        FOR EACH ROW EXECUTE FUNCTION prevent_sealed_dataset_version_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER dataset_versions_sealed_immutable ON dataset_versions")
    op.execute("DROP FUNCTION prevent_sealed_dataset_version_mutation()")
    op.drop_index(
        "ix_dataset_quality_reports_version_created", table_name="dataset_quality_reports"
    )
    op.drop_table("dataset_quality_reports")
    op.drop_index("ix_dataset_items_version_domain", table_name="dataset_items")
    op.drop_index("ix_dataset_items_version_split", table_name="dataset_items")
    op.drop_table("dataset_items")
    op.drop_index("ix_dataset_versions_dataset_created", table_name="dataset_versions")
    op.drop_table("dataset_versions")
    op.drop_index("ix_datasets_project_updated", table_name="datasets")
    op.drop_table("datasets")
