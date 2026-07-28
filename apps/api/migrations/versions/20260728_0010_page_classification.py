"""Persist deterministic page classification and representative selection.

Revision ID: 20260728_0010
Revises: 20260728_0009
Create Date: 2026-07-28 00:00:04+00:00
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0010"
down_revision: str | None = "20260728_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scan_campaigns",
        sa.Column(
            "include_restricted_representatives",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    columns: tuple[sa.Column[Any], ...] = (
        sa.Column("page_type", sa.String(length=32)),
        sa.Column("page_type_score", sa.Float()),
        sa.Column(
            "classification_features",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "classification_explanation",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("classifier", sa.String(length=64)),
        sa.Column("classifier_version", sa.Integer()),
        sa.Column("classified_at", sa.DateTime(timezone=True)),
        sa.Column(
            "representative_selected", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("representative_rank", sa.Integer()),
        sa.Column("representative_score", sa.Float()),
        sa.Column(
            "selection_explanation",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("selector", sa.String(length=64)),
        sa.Column("selector_version", sa.Integer()),
        sa.Column(
            "manual_selection", sa.String(length=16), server_default="automatic", nullable=False
        ),
        sa.Column("manual_selection_reason", sa.String(length=500)),
        sa.Column("manual_selected_by_user_id", sa.Uuid()),
        sa.Column("manual_selected_at", sa.DateTime(timezone=True)),
    )
    for column in columns:
        op.add_column("crawl_pages", column)
    op.create_foreign_key(
        "fk_crawl_pages_manual_selected_by_user_id_users",
        "crawl_pages",
        "users",
        ["manual_selected_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_crawl_pages_page_type_allowed",
        "crawl_pages",
        "page_type IS NULL OR page_type IN ("
        "'homepage', 'about', 'services', 'product', 'features', 'pricing', 'contact', "
        "'documentation', 'blog-index', 'article', 'case-study', 'careers', 'legal', "
        "'authentication', 'unknown')",
    )
    op.create_check_constraint(
        "ck_crawl_pages_manual_selection_allowed",
        "crawl_pages",
        "manual_selection IN ('automatic', 'include', 'exclude')",
    )
    op.create_check_constraint(
        "ck_crawl_pages_representative_rank_positive",
        "crawl_pages",
        "representative_rank IS NULL OR representative_rank >= 1",
    )
    op.create_index(
        "ix_crawl_pages_campaign_page_type", "crawl_pages", ["campaign_id", "page_type"]
    )
    op.create_index(
        "ix_crawl_pages_campaign_representative",
        "crawl_pages",
        ["campaign_id", "representative_selected", "representative_rank"],
    )


def downgrade() -> None:
    op.drop_index("ix_crawl_pages_campaign_representative", table_name="crawl_pages")
    op.drop_index("ix_crawl_pages_campaign_page_type", table_name="crawl_pages")
    op.drop_constraint("ck_crawl_pages_representative_rank_positive", "crawl_pages", type_="check")
    op.drop_constraint("ck_crawl_pages_manual_selection_allowed", "crawl_pages", type_="check")
    op.drop_constraint("ck_crawl_pages_page_type_allowed", "crawl_pages", type_="check")
    op.drop_constraint(
        "fk_crawl_pages_manual_selected_by_user_id_users", "crawl_pages", type_="foreignkey"
    )
    for name in reversed(
        (
            "page_type",
            "page_type_score",
            "classification_features",
            "classification_explanation",
            "classifier",
            "classifier_version",
            "classified_at",
            "representative_selected",
            "representative_rank",
            "representative_score",
            "selection_explanation",
            "selector",
            "selector_version",
            "manual_selection",
            "manual_selection_reason",
            "manual_selected_by_user_id",
            "manual_selected_at",
        )
    ):
        op.drop_column("crawl_pages", name)
    op.drop_column("scan_campaigns", "include_restricted_representatives")
