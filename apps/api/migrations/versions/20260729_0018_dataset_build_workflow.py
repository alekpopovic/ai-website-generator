"""Add durable dataset build workflow attempts.

Revision ID: 20260729_0018
Revises: 20260728_0017
Create Date: 2026-07-29 00:00:12+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260729_0018"
down_revision: str | None = "20260728_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dataset_builds",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("quality_policy", postgresql.JSONB(), nullable=False),
        sa.Column("enqueue_missing_embeddings", sa.Boolean(), nullable=False),
        sa.Column("excluded_counts", postgresql.JSONB(), nullable=False),
        sa.Column("workflow_id", sa.String(300)),
        sa.Column("workflow_run_id", sa.String(100)),
        sa.Column("workflow_attempt", sa.Integer(), nullable=False),
        sa.Column("failure_code", sa.String(100)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'cancelling', 'cancelled', 'failed', 'succeeded')",
            name=op.f("ck_dataset_builds_status_allowed"),
        ),
        sa.CheckConstraint(
            "workflow_attempt >= 1", name=op.f("ck_dataset_builds_workflow_attempt_positive")
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["dataset_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_builds")),
        sa.UniqueConstraint(
            "dataset_version_id",
            "idempotency_key",
            name=op.f("uq_dataset_builds_dataset_version_id_idempotency_key"),
        ),
    )
    op.create_index(
        "ix_dataset_builds_project_created", "dataset_builds", ["project_id", "created_at"]
    )
    op.create_index(
        "ix_dataset_builds_version_status",
        "dataset_builds",
        ["dataset_version_id", "status"],
    )
    op.create_index(
        "uq_dataset_builds_active_version",
        "dataset_builds",
        ["dataset_version_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running', 'cancelling')"),
    )
    op.add_column("dataset_quality_reports", sa.Column("dataset_build_id", sa.Uuid()))
    op.create_foreign_key(
        op.f("fk_dataset_quality_reports_dataset_build_id_dataset_builds"),
        "dataset_quality_reports",
        "dataset_builds",
        ["dataset_build_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        op.f("uq_dataset_quality_reports_dataset_build_id"),
        "dataset_quality_reports",
        ["dataset_build_id"],
    )
    op.add_column("embedding_runs", sa.Column("dataset_id", sa.Uuid()))
    op.add_column("embedding_runs", sa.Column("dataset_version_id", sa.Uuid()))
    op.create_foreign_key(
        op.f("fk_embedding_runs_dataset_id_datasets"),
        "embedding_runs",
        "datasets",
        ["dataset_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_embedding_runs_dataset_version_id_dataset_versions"),
        "embedding_runs",
        "dataset_versions",
        ["dataset_version_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        op.f("ck_embedding_runs_dataset_lineage_complete"),
        "embedding_runs",
        "(dataset_id IS NULL) = (dataset_version_id IS NULL)",
    )
    op.create_index(
        "ix_embedding_runs_dataset_version",
        "embedding_runs",
        ["dataset_version_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_embedding_runs_dataset_version", table_name="embedding_runs")
    op.drop_constraint(
        op.f("ck_embedding_runs_dataset_lineage_complete"),
        "embedding_runs",
        type_="check",
    )
    op.drop_constraint(
        op.f("fk_embedding_runs_dataset_version_id_dataset_versions"),
        "embedding_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_embedding_runs_dataset_id_datasets"),
        "embedding_runs",
        type_="foreignkey",
    )
    op.drop_column("embedding_runs", "dataset_version_id")
    op.drop_column("embedding_runs", "dataset_id")
    op.drop_constraint(
        op.f("uq_dataset_quality_reports_dataset_build_id"),
        "dataset_quality_reports",
        type_="unique",
    )
    op.drop_constraint(
        op.f("fk_dataset_quality_reports_dataset_build_id_dataset_builds"),
        "dataset_quality_reports",
        type_="foreignkey",
    )
    op.drop_column("dataset_quality_reports", "dataset_build_id")
    op.drop_index("uq_dataset_builds_active_version", table_name="dataset_builds")
    op.drop_index("ix_dataset_builds_version_status", table_name="dataset_builds")
    op.drop_index("ix_dataset_builds_project_created", table_name="dataset_builds")
    op.drop_table("dataset_builds")
