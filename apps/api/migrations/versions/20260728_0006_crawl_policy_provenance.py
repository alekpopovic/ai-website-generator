"""Persist effective crawl policy and require robots compliance.

Revision ID: 20260728_0006
Revises: 20260727_0005
Create Date: 2026-07-28 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0006"
down_revision: str | None = "20260727_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add domain policy records and page-level decision evidence."""
    op.execute("UPDATE scan_campaigns SET respect_robots_txt = TRUE WHERE NOT respect_robots_txt")
    op.create_check_constraint(
        "ck_scan_campaigns_robots_required", "scan_campaigns", "respect_robots_txt IS TRUE"
    )
    op.add_column(
        "scan_campaigns",
        sa.Column(
            "crawler_user_agent",
            sa.String(length=256),
            server_default="AIWebsiteGeneratorBot/1.0",
            nullable=False,
        ),
    )
    op.add_column(
        "scan_campaigns",
        sa.Column(
            "tracking_query_parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text(
                '\'["utm_*", "dclid", "fbclid", "gclid", "mc_cid", '
                '"mc_eid", "msclkid", "ref", "referrer"]\'::jsonb'
            ),
            nullable=False,
        ),
    )
    op.create_table(
        "crawl_policy_records",
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("source_domain", sa.String(length=253), nullable=False),
        sa.Column("robots_url", sa.String(length=2048), nullable=False),
        sa.Column("final_robots_url", sa.String(length=2048), nullable=False),
        sa.Column("fetch_status", sa.String(length=32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64)),
        sa.Column("crawler_user_agent", sa.String(length=256), nullable=False),
        sa.Column("crawl_delay_seconds", sa.Float()),
        sa.Column("redirect_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "sitemap_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "effective_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "fetch_status IN ('fetched', 'not_found', 'unavailable', 'invalid', "
            "'oversized', 'redirect_limit_exceeded', 'blocked')",
            name="ck_crawl_policy_records_fetch_status_allowed",
        ),
        sa.CheckConstraint(
            "redirect_count BETWEEN 0 AND 20",
            name="ck_crawl_policy_records_redirect_count_valid",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["scan_campaigns.id"],
            name="fk_crawl_policy_records_campaign_id_scan_campaigns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["scan_targets.id"],
            name="fk_crawl_policy_records_target_id_scan_targets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_crawl_policy_records"),
        sa.UniqueConstraint(
            "campaign_id", "target_id", name="uq_crawl_policy_records_campaign_id_target_id"
        ),
    )
    op.create_index(
        "ix_crawl_policy_records_campaign_id_source_domain",
        "crawl_policy_records",
        ["campaign_id", "source_domain"],
    )
    op.add_column("crawl_pages", sa.Column("crawl_policy_record_id", sa.Uuid(), nullable=True))
    op.add_column(
        "crawl_pages", sa.Column("crawl_decision_code", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "crawl_pages",
        sa.Column(
            "crawl_policy_provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_crawl_pages_crawl_policy_record_id_crawl_policy_records",
        "crawl_pages",
        "crawl_policy_records",
        ["crawl_policy_record_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Remove crawl policy provenance while retaining existing scan records."""
    op.drop_constraint(
        "fk_crawl_pages_crawl_policy_record_id_crawl_policy_records",
        "crawl_pages",
        type_="foreignkey",
    )
    op.drop_column("crawl_pages", "crawl_policy_provenance")
    op.drop_column("crawl_pages", "crawl_decision_code")
    op.drop_column("crawl_pages", "crawl_policy_record_id")
    op.drop_index(
        "ix_crawl_policy_records_campaign_id_source_domain", table_name="crawl_policy_records"
    )
    op.drop_table("crawl_policy_records")
    op.drop_column("scan_campaigns", "tracking_query_parameters")
    op.drop_column("scan_campaigns", "crawler_user_agent")
    op.drop_constraint("ck_scan_campaigns_robots_required", "scan_campaigns", type_="check")
