"""Persist deterministic browser semantic extraction summaries.

Revision ID: 20260728_0012
Revises: 20260728_0011
Create Date: 2026-07-28 00:00:06+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0012"
down_revision: str | None = "20260728_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("page_scans", sa.Column("semantic_snapshot_artifact_key", sa.String(length=1024)))
    op.add_column("page_scans", sa.Column("extractor_version", sa.String(length=64)))
    op.add_column("page_scans", sa.Column("extracted_node_count", sa.Integer()))
    op.add_column("page_scans", sa.Column("extraction_payload_bytes", sa.Integer()))
    op.add_column(
        "page_scans",
        sa.Column("extraction_truncated", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "page_scans",
        sa.Column(
            "semantic_snapshot_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_page_scans_extracted_node_count_nonnegative"),
        "page_scans",
        "extracted_node_count IS NULL OR extracted_node_count >= 0",
    )
    op.create_check_constraint(
        op.f("ck_page_scans_extraction_payload_bytes_nonnegative"),
        "page_scans",
        "extraction_payload_bytes IS NULL OR extraction_payload_bytes >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_page_scans_extraction_payload_bytes_nonnegative"),
        "page_scans",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_page_scans_extracted_node_count_nonnegative"),
        "page_scans",
        type_="check",
    )
    for name in reversed(
        (
            "semantic_snapshot_artifact_key",
            "extractor_version",
            "extracted_node_count",
            "extraction_payload_bytes",
            "extraction_truncated",
            "semantic_snapshot_summary",
        )
    ):
        op.drop_column("page_scans", name)
