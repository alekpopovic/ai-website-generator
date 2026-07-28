"""Persist idempotent bounded Playwright capture metadata.

Revision ID: 20260728_0011
Revises: 20260728_0010
Create Date: 2026-07-28 00:00:05+00:00
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0011"
down_revision: str | None = "20260728_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns: tuple[sa.Column[Any], ...] = (
        sa.Column("viewport_screenshot_artifact_key", sa.String(length=1024)),
        sa.Column("configuration_hash", sa.String(length=64)),
        sa.Column("capture_schema_version", sa.Integer()),
        sa.Column("browser_version", sa.String(length=64)),
        sa.Column("final_url", sa.String(length=2048)),
        sa.Column(
            "artifact_checksums",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "response_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("page_title", sa.String(length=500)),
        sa.Column("meta_description", sa.String(length=1000)),
        sa.Column("canonical_url", sa.String(length=2048)),
        sa.Column("language", sa.String(length=35)),
        sa.Column("visible_text_summary", sa.String(length=4000)),
        sa.Column(
            "console_errors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "page_errors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "failed_requests",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "external_host_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("document_width", sa.Integer()),
        sa.Column("document_height", sa.Integer()),
        sa.Column("screenshot_width", sa.Integer()),
        sa.Column("screenshot_height", sa.Integer()),
        sa.Column("full_page_truncated", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    for column in columns:
        op.add_column("page_scans", column)
    op.create_check_constraint(
        "ck_page_scans_capture_schema_version_positive",
        "page_scans",
        "capture_schema_version IS NULL OR capture_schema_version >= 1",
    )
    op.create_check_constraint(
        "ck_page_scans_document_width_positive",
        "page_scans",
        "document_width IS NULL OR document_width >= 1",
    )
    op.create_check_constraint(
        "ck_page_scans_document_height_positive",
        "page_scans",
        "document_height IS NULL OR document_height >= 1",
    )
    op.create_index("ix_page_scans_configuration_hash", "page_scans", ["configuration_hash"])
    op.create_unique_constraint(
        "uq_page_scans_crawl_page_id_viewport_configuration_hash",
        "page_scans",
        ["crawl_page_id", "viewport", "configuration_hash"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_page_scans_crawl_page_id_viewport_configuration_hash",
        "page_scans",
        type_="unique",
    )
    op.drop_index("ix_page_scans_configuration_hash", table_name="page_scans")
    op.drop_constraint("ck_page_scans_document_height_positive", "page_scans", type_="check")
    op.drop_constraint("ck_page_scans_document_width_positive", "page_scans", type_="check")
    op.drop_constraint("ck_page_scans_capture_schema_version_positive", "page_scans", type_="check")
    for name in reversed(
        (
            "viewport_screenshot_artifact_key",
            "configuration_hash",
            "capture_schema_version",
            "browser_version",
            "final_url",
            "artifact_checksums",
            "response_metadata",
            "page_title",
            "meta_description",
            "canonical_url",
            "language",
            "visible_text_summary",
            "console_errors",
            "page_errors",
            "failed_requests",
            "external_host_manifest",
            "document_width",
            "document_height",
            "screenshot_width",
            "screenshot_height",
            "full_page_truncated",
        )
    ):
        op.drop_column("page_scans", name)
