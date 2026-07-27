"""Persist normalized crawler results and idempotent failures.

Revision ID: 20260728_0007
Revises: 20260728_0006
Create Date: 2026-07-28 00:00:01+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0007"
down_revision: str | None = "20260728_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scan_campaigns",
        sa.Column("store_raw_html", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    for column in (
        sa.Column("final_url", sa.String(length=2048)),
        sa.Column("title", sa.String(length=500)),
        sa.Column("meta_description", sa.String(length=1000)),
        sa.Column("language", sa.String(length=35)),
        sa.Column("content_length", sa.Integer()),
        sa.Column("discovery_source", sa.String(length=32), server_default="link", nullable=False),
        sa.Column("parent_url", sa.String(length=2048)),
    ):
        op.add_column("crawl_pages", column)
    op.create_check_constraint(
        "ck_crawl_pages_content_length_non_negative",
        "crawl_pages",
        "content_length IS NULL OR content_length >= 0",
    )
    op.create_check_constraint(
        "ck_crawl_pages_discovery_source_allowed",
        "crawl_pages",
        "discovery_source IN ('seed', 'sitemap', 'link')",
    )
    op.add_column("scan_failures", sa.Column("failure_key", sa.String(length=64)))
    op.create_unique_constraint(
        "uq_scan_failures_campaign_id_failure_key",
        "scan_failures",
        ["campaign_id", "failure_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_scan_failures_campaign_id_failure_key", "scan_failures", type_="unique")
    op.drop_column("scan_failures", "failure_key")
    op.drop_constraint("ck_crawl_pages_discovery_source_allowed", "crawl_pages", type_="check")
    op.drop_constraint("ck_crawl_pages_content_length_non_negative", "crawl_pages", type_="check")
    for name in (
        "parent_url",
        "discovery_source",
        "content_length",
        "language",
        "meta_description",
        "title",
        "final_url",
    ):
        op.drop_column("crawl_pages", name)
    op.drop_column("scan_campaigns", "store_raw_html")
