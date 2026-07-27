"""Persist canonical discovery metadata and query ordering policy.

Revision ID: 20260728_0008
Revises: 20260728_0007
Create Date: 2026-07-28 00:00:02+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0008"
down_revision: str | None = "20260728_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scan_campaigns",
        sa.Column(
            "query_parameter_ordering",
            sa.String(length=16),
            server_default="sorted",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_scan_campaigns_query_parameter_ordering_allowed",
        "scan_campaigns",
        "query_parameter_ordering IN ('preserve', 'sorted')",
    )

    op.drop_constraint("ck_crawl_pages_discovery_source_allowed", "crawl_pages", type_="check")
    op.execute(
        "UPDATE crawl_pages SET discovery_source = 'submitted_root' WHERE discovery_source = 'seed'"
    )
    op.execute(
        "UPDATE crawl_pages SET discovery_source = 'html_link' WHERE discovery_source = 'link'"
    )
    op.create_check_constraint(
        "ck_crawl_pages_discovery_source_allowed",
        "crawl_pages",
        "discovery_source IN ("
        "'submitted_root', 'robots_sitemap', 'sitemap', 'html_link', 'canonical')",
    )
    op.alter_column("crawl_pages", "discovery_source", server_default="html_link")
    op.add_column("crawl_pages", sa.Column("declared_canonical_url", sa.String(length=2048)))
    op.add_column(
        "crawl_pages",
        sa.Column(
            "hreflang_links",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("crawl_pages", sa.Column("last_modified_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("crawl_pages", "last_modified_at")
    op.drop_column("crawl_pages", "hreflang_links")
    op.drop_column("crawl_pages", "declared_canonical_url")
    op.drop_constraint("ck_crawl_pages_discovery_source_allowed", "crawl_pages", type_="check")
    op.execute(
        "UPDATE crawl_pages SET discovery_source = 'seed' WHERE discovery_source = 'submitted_root'"
    )
    op.execute(
        "UPDATE crawl_pages SET discovery_source = 'link' WHERE discovery_source IN ('html_link', 'canonical')"
    )
    op.execute(
        "UPDATE crawl_pages SET discovery_source = 'sitemap' WHERE discovery_source = 'robots_sitemap'"
    )
    op.create_check_constraint(
        "ck_crawl_pages_discovery_source_allowed",
        "crawl_pages",
        "discovery_source IN ('seed', 'sitemap', 'link')",
    )
    op.alter_column("crawl_pages", "discovery_source", server_default="link")
    op.drop_constraint(
        "ck_scan_campaigns_query_parameter_ordering_allowed",
        "scan_campaigns",
        type_="check",
    )
    op.drop_column("scan_campaigns", "query_parameter_ordering")
