"""Add a controlled workflow type to durable job events.

Revision ID: 20260728_0016
Revises: 20260728_0015
Create Date: 2026-07-28 00:00:10+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0016"
down_revision: str | None = "20260728_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job_events",
        sa.Column("job_type", sa.String(32), server_default="scan_campaign", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_job_events_job_type_allowed"),
        "job_events",
        "job_type IN ('scan_campaign', 'dataset_build', 'generation', 'validation', 'training')",
    )
    op.create_index(
        "ix_job_events_job_id_sequence", "job_events", ["job_id", "sequence"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_job_events_job_id_sequence", table_name="job_events")
    op.drop_constraint(op.f("ck_job_events_job_type_allowed"), "job_events", type_="check")
    op.drop_column("job_events", "job_type")
