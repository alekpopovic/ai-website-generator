"""Add historical normalized analysis profiles and section patterns.

Revision ID: 20260728_0014
Revises: 20260728_0013
Create Date: 2026-07-28 00:00:08+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import SchemaItem

revision: str = "20260728_0014"
down_revision: str | None = "20260728_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPROVAL = "approval_state IN ('needs_review', 'approved', 'rejected')"
PROVENANCE = "provenance_state IN ('authorized', 'restricted', 'removal_pending', 'removed')"


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("source_website_id", sa.Uuid(), nullable=False),
        sa.Column("source_page_id", sa.Uuid()),
        sa.Column("output_kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("analyzer_version", sa.String(100), nullable=False),
        sa.Column("strategy", sa.String(64), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("model_digest", sa.String(200), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("used_fallback", sa.Boolean(), nullable=False),
        sa.Column("provenance_state", sa.String(32), nullable=False),
        sa.Column("result_sha256", sa.String(64)),
        sa.Column("failure_code", sa.String(100)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "output_kind IN ('page', 'website')", name=op.f("ck_analysis_runs_output_kind_allowed")
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed', 'cancelled')",
            name=op.f("ck_analysis_runs_status_allowed"),
        ),
        sa.CheckConstraint(PROVENANCE, name=op.f("ck_analysis_runs_provenance_state_allowed")),
        sa.CheckConstraint(
            "schema_version >= 1", name=op.f("ck_analysis_runs_schema_version_positive")
        ),
        sa.CheckConstraint("attempts >= 1", name=op.f("ck_analysis_runs_attempts_positive")),
        sa.CheckConstraint("latency_ms >= 0", name=op.f("ck_analysis_runs_latency_nonnegative")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["scan_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_website_id"], ["scan_targets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_page_id"], ["crawl_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_runs")),
    )
    op.create_index(
        "ix_analysis_runs_project_created", "analysis_runs", ["project_id", "created_at"]
    )
    op.create_index(
        "ix_analysis_runs_page_created", "analysis_runs", ["source_page_id", "created_at"]
    )

    _create_profile_table("page_profiles", page=True)
    _create_profile_table("website_profiles", page=False)

    op.create_table(
        "section_patterns",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("source_website_id", sa.Uuid(), nullable=False),
        sa.Column("source_page_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
        sa.Column("page_profile_id", sa.Uuid(), nullable=False),
        sa.Column("duplicate_of_id", sa.Uuid()),
        sa.Column("pattern_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("section_order", sa.Integer(), nullable=False),
        sa.Column("section_type", sa.String(32), nullable=False),
        sa.Column("layout", sa.String(32), nullable=False),
        sa.Column("style_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("language", sa.String(35), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("analyzer_version", sa.String(100), nullable=False),
        sa.Column("model_digest", sa.String(200), nullable=False),
        sa.Column("approval_state", sa.String(32), nullable=False),
        sa.Column("provenance_state", sa.String(32), nullable=False),
        sa.Column("retrieval_document", sa.String(4000), nullable=False),
        sa.Column("pattern_hash", sa.String(64), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_note", sa.String(500)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(APPROVAL, name=op.f("ck_section_patterns_approval_state_allowed")),
        sa.CheckConstraint(PROVENANCE, name=op.f("ck_section_patterns_provenance_state_allowed")),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1", name=op.f("ck_section_patterns_confidence_valid")
        ),
        sa.CheckConstraint(
            "section_order BETWEEN 0 AND 255", name=op.f("ck_section_patterns_section_order_valid")
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["scan_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_website_id"], ["scan_targets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_page_id"], ["crawl_pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["page_profile_id"], ["page_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["duplicate_of_id"], ["section_patterns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_section_patterns")),
        sa.UniqueConstraint(
            "page_profile_id",
            "section_order",
            name=op.f("uq_section_patterns_page_profile_id_section_order"),
        ),
    )
    op.create_index(
        "ix_section_patterns_project_type", "section_patterns", ["project_id", "section_type"]
    )
    op.create_index("ix_section_patterns_hash", "section_patterns", ["project_id", "pattern_hash"])
    op.create_index(
        "ix_section_patterns_page_profile", "section_patterns", ["page_profile_id", "section_order"]
    )
    op.create_index(
        "ix_section_patterns_style_tags", "section_patterns", ["style_tags"], postgresql_using="gin"
    )


def _create_profile_table(name: str, *, page: bool) -> None:
    columns: list[SchemaItem] = [
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("source_website_id", sa.Uuid(), nullable=False),
    ]
    if page:
        columns.append(sa.Column("source_page_id", sa.Uuid(), nullable=False))
    columns.extend(
        [
            sa.Column("analysis_run_id", sa.Uuid(), nullable=False),
            sa.Column("profile_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        ]
    )
    if page:
        columns.append(sa.Column("page_type", sa.String(32), nullable=False))
    columns.extend(
        [
            sa.Column("category", sa.String(64), nullable=False),
            sa.Column("language", sa.String(35), nullable=False),
            sa.Column("style_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("schema_version", sa.Integer(), nullable=False),
            sa.Column("analyzer_version", sa.String(100), nullable=False),
            sa.Column("model_digest", sa.String(200), nullable=False),
            sa.Column("approval_state", sa.String(32), nullable=False),
            sa.Column("provenance_state", sa.String(32), nullable=False),
            sa.Column("is_current", sa.Boolean(), nullable=False),
            sa.Column("reviewed_by_user_id", sa.Uuid()),
            sa.Column("reviewed_at", sa.DateTime(timezone=True)),
            sa.Column("review_note", sa.String(500)),
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.CheckConstraint(APPROVAL, name=op.f(f"ck_{name}_approval_state_allowed")),
            sa.CheckConstraint(PROVENANCE, name=op.f(f"ck_{name}_provenance_state_allowed")),
            sa.CheckConstraint(
                "confidence BETWEEN 0 AND 1", name=op.f(f"ck_{name}_confidence_valid")
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["campaign_id"], ["scan_campaigns.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_website_id"], ["scan_targets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
            sa.UniqueConstraint("analysis_run_id", name=op.f(f"uq_{name}_analysis_run_id")),
        ]
    )
    if page:
        columns.append(
            sa.ForeignKeyConstraint(["source_page_id"], ["crawl_pages.id"], ondelete="CASCADE")
        )
    op.create_table(name, *columns)
    current_key = "source_page_id" if page else "source_website_id"
    op.create_index(f"ix_{name}_project_current", name, ["project_id", "is_current"])
    if page:
        op.create_index(f"ix_{name}_page_type", name, ["project_id", "page_type"])
    op.create_index(f"ix_{name}_style_tags", name, ["style_tags"], postgresql_using="gin")
    op.create_index(
        f"uq_{name}_current_{current_key}",
        name,
        [current_key],
        unique=True,
        postgresql_where=sa.text("is_current IS TRUE"),
    )


def downgrade() -> None:
    op.drop_table("section_patterns")
    op.drop_table("website_profiles")
    op.drop_table("page_profiles")
    op.drop_table("analysis_runs")
