"""Add deterministic page fingerprints and duplicate relationships.

Revision ID: 20260728_0009
Revises: 20260728_0008
Create Date: 2026-07-28 00:00:03+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0009"
down_revision: str | None = "20260728_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STRING_64_COLUMNS = (
    "normalized_url_sha256",
    "visible_text_sha256",
    "dom_structure_sha256",
    "heading_sequence_sha256",
    "link_structure_sha256",
    "dom_template_sha256",
    "normalized_content_sha256",
    "exact_group_key",
    "near_group_key",
    "template_group_key",
)


def upgrade() -> None:
    op.add_column("crawl_pages", sa.Column("fingerprint_algorithm", sa.String(length=64)))
    op.add_column("crawl_pages", sa.Column("fingerprint_version", sa.Integer()))
    for name in _STRING_64_COLUMNS:
        op.add_column("crawl_pages", sa.Column(name, sa.String(length=64)))
    op.add_column("crawl_pages", sa.Column("semantic_simhash", sa.String(length=16)))
    op.add_column("crawl_pages", sa.Column("normalized_text_length", sa.Integer()))
    for name in (
        "exact_duplicate_of_id",
        "near_duplicate_of_id",
        "template_representative_id",
    ):
        op.add_column("crawl_pages", sa.Column(name, sa.Uuid()))
        op.create_foreign_key(
            f"fk_crawl_pages_{name}_crawl_pages",
            "crawl_pages",
            "crawl_pages",
            [name],
            ["id"],
            ondelete="SET NULL",
        )
    op.add_column("crawl_pages", sa.Column("fingerprinted_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_crawl_pages_fingerprint_version_positive",
        "crawl_pages",
        "fingerprint_version IS NULL OR fingerprint_version >= 1",
    )
    op.create_check_constraint(
        "ck_crawl_pages_normalized_text_length_non_negative",
        "crawl_pages",
        "normalized_text_length IS NULL OR normalized_text_length >= 0",
    )
    op.create_index(
        "ix_crawl_pages_campaign_content_fingerprint",
        "crawl_pages",
        ["campaign_id", "normalized_content_sha256"],
    )
    op.create_index(
        "ix_crawl_pages_campaign_semantic_simhash",
        "crawl_pages",
        ["campaign_id", "semantic_simhash"],
    )
    op.create_index(
        "ix_crawl_pages_campaign_template_fingerprint",
        "crawl_pages",
        ["campaign_id", "dom_template_sha256"],
    )
    for name in (
        "exact_duplicate_of_id",
        "near_duplicate_of_id",
        "template_representative_id",
    ):
        op.create_index(f"ix_crawl_pages_{name}", "crawl_pages", [name])


def downgrade() -> None:
    for name in (
        "template_representative_id",
        "near_duplicate_of_id",
        "exact_duplicate_of_id",
    ):
        op.drop_index(f"ix_crawl_pages_{name}", table_name="crawl_pages")
    op.drop_index("ix_crawl_pages_campaign_template_fingerprint", table_name="crawl_pages")
    op.drop_index("ix_crawl_pages_campaign_semantic_simhash", table_name="crawl_pages")
    op.drop_index("ix_crawl_pages_campaign_content_fingerprint", table_name="crawl_pages")
    op.drop_constraint(
        "ck_crawl_pages_normalized_text_length_non_negative", "crawl_pages", type_="check"
    )
    op.drop_constraint("ck_crawl_pages_fingerprint_version_positive", "crawl_pages", type_="check")
    op.drop_column("crawl_pages", "fingerprinted_at")
    for name in (
        "template_representative_id",
        "near_duplicate_of_id",
        "exact_duplicate_of_id",
    ):
        op.drop_constraint(f"fk_crawl_pages_{name}_crawl_pages", "crawl_pages", type_="foreignkey")
        op.drop_column("crawl_pages", name)
    op.drop_column("crawl_pages", "normalized_text_length")
    op.drop_column("crawl_pages", "semantic_simhash")
    for name in reversed(_STRING_64_COLUMNS):
        op.drop_column("crawl_pages", name)
    op.drop_column("crawl_pages", "fingerprint_version")
    op.drop_column("crawl_pages", "fingerprint_algorithm")
