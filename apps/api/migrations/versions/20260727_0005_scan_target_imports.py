"""Add durable, row-level scan target imports.

Revision ID: 20260727_0005
Revises: 20260727_0004
Create Date: 2026-07-27
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260727_0005"
down_revision: str | None = "20260727_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _identity_columns(*, timestamps: bool = True) -> tuple[sa.Column[Any], ...]:
    columns: list[sa.Column[Any]] = [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    ]
    if timestamps:
        columns.extend(
            [
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                    nullable=False,
                ),
                sa.Column("version", sa.Integer(), server_default="1", nullable=False),
            ]
        )
    return tuple(columns)


def upgrade() -> None:
    op.create_table(
        "scan_target_imports",
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("filename", sa.String(length=255)),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("authorization_attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("allow_ip_literals", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("processed_rows", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("invalid_count", sa.Integer(), nullable=False),
        sa.Column("blocked_count", sa.Integer(), nullable=False),
        sa.Column("already_present_count", sa.Integer(), nullable=False),
        sa.Column("committed_count", sa.Integer(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        *_identity_columns(),
        sa.CheckConstraint(
            "status IN ('validating', 'completed', 'committed', 'failed')",
            name="ck_scan_target_imports_status_allowed",
        ),
        sa.CheckConstraint(
            "source_type IN ('paste', 'text', 'csv')",
            name="ck_scan_target_imports_source_type_allowed",
        ),
        sa.CheckConstraint(
            "total_rows BETWEEN 0 AND 50000",
            name="ck_scan_target_imports_total_rows_bounded",
        ),
        sa.CheckConstraint(
            "processed_rows BETWEEN 0 AND 50000",
            name="ck_scan_target_imports_processed_rows_bounded",
        ),
        sa.CheckConstraint(
            "accepted_count >= 0 AND duplicate_count >= 0 AND invalid_count >= 0 "
            "AND blocked_count >= 0 AND already_present_count >= 0 AND committed_count >= 0",
            name="ck_scan_target_imports_counts_non_negative",
        ),
        sa.CheckConstraint(
            "committed_count <= accepted_count",
            name="ck_scan_target_imports_committed_not_above_accepted",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["scan_campaigns.id"],
            name="fk_scan_target_imports_campaign_id_scan_campaigns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name="fk_scan_target_imports_requested_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scan_target_imports"),
    )
    op.create_index(
        "ix_scan_target_imports_campaign_id_created_at",
        "scan_target_imports",
        ["campaign_id", "created_at"],
    )

    op.add_column("scan_targets", sa.Column("import_id", sa.Uuid()))
    op.add_column("scan_targets", sa.Column("import_row_number", sa.Integer()))
    op.add_column(
        "scan_targets",
        sa.Column(
            "import_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_foreign_key(
        "fk_scan_targets_import_id_scan_target_imports",
        "scan_targets",
        "scan_target_imports",
        ["import_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_scan_targets_campaign_id_source_domain",
        "scan_targets",
        ["campaign_id", "source_domain"],
    )

    op.create_table(
        "scan_target_import_rows",
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_value", sa.String(length=2048), nullable=False),
        sa.Column("normalized_url", sa.String(length=2048)),
        sa.Column("source_domain", sa.String(length=253)),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64)),
        sa.Column("reason_message", sa.String(length=500)),
        sa.Column("target_id", sa.Uuid()),
        *_identity_columns(timestamps=False),
        sa.CheckConstraint(
            "outcome IN ('accepted', 'duplicate', 'invalid', 'blocked', 'already_present')",
            name="ck_scan_target_import_rows_outcome_allowed",
        ),
        sa.CheckConstraint(
            "row_number BETWEEN 1 AND 50000",
            name="ck_scan_target_import_rows_row_number_bounded",
        ),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["scan_target_imports.id"],
            name="fk_scan_target_import_rows_import_id_scan_target_imports",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["scan_targets.id"],
            name="fk_scan_target_import_rows_target_id_scan_targets",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scan_target_import_rows"),
        sa.UniqueConstraint(
            "import_id",
            "row_number",
            name="uq_scan_target_import_rows_import_id_row_number",
        ),
    )
    op.create_index(
        "ix_scan_target_import_rows_import_id_outcome",
        "scan_target_import_rows",
        ["import_id", "outcome"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scan_target_import_rows_import_id_outcome", table_name="scan_target_import_rows"
    )
    op.drop_table("scan_target_import_rows")
    op.drop_constraint(
        "fk_scan_targets_import_id_scan_target_imports", "scan_targets", type_="foreignkey"
    )
    op.drop_index("ix_scan_targets_campaign_id_source_domain", table_name="scan_targets")
    op.drop_column("scan_targets", "import_metadata")
    op.drop_column("scan_targets", "import_row_number")
    op.drop_column("scan_targets", "import_id")
    op.drop_index("ix_scan_target_imports_campaign_id_created_at", table_name="scan_target_imports")
    op.drop_table("scan_target_imports")
