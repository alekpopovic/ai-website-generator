"""Add durable embedding runs, per-collection status, and failure history.

Revision ID: 20260728_0015
Revises: 20260728_0014
Create Date: 2026-07-28 00:00:09+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0015"
down_revision: str | None = "20260728_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "section_patterns",
        sa.Column("retrieval_expires_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "section_patterns",
        sa.Column("retrieval_removed_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "section_patterns",
        sa.Column("legally_suppressed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "embedding_runs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid()),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("promote_alias", sa.Boolean(), nullable=False),
        sa.Column("collection_alias", sa.String(64), nullable=False),
        sa.Column("physical_collection", sa.String(240)),
        sa.Column("embedding_provider", sa.String(32)),
        sa.Column("embedding_model", sa.String(200)),
        sa.Column("embedding_model_digest", sa.String(128)),
        sa.Column("serialization_schema_version", sa.Integer(), nullable=False),
        sa.Column("vector_name", sa.String(64), nullable=False),
        sa.Column("dimensions", sa.Integer()),
        sa.Column("total_patterns", sa.Integer(), nullable=False),
        sa.Column("processed_patterns", sa.Integer(), nullable=False),
        sa.Column("indexed_patterns", sa.Integer(), nullable=False),
        sa.Column("deleted_patterns", sa.Integer(), nullable=False),
        sa.Column("failed_patterns", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.String(255)),
        sa.Column("workflow_run_id", sa.String(255)),
        sa.Column("failure_code", sa.String(100)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("alias_switched_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('incremental', 'reindex')", name=op.f("ck_embedding_runs_kind_allowed")
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_embedding_runs_status_allowed"),
        ),
        sa.CheckConstraint(
            "batch_size BETWEEN 1 AND 256", name=op.f("ck_embedding_runs_batch_size_valid")
        ),
        sa.CheckConstraint(
            "total_patterns >= 0 AND processed_patterns >= 0 AND indexed_patterns >= 0 AND deleted_patterns >= 0 AND failed_patterns >= 0",
            name=op.f("ck_embedding_runs_counts_nonnegative"),
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embedding_runs")),
        sa.UniqueConstraint(
            "project_id",
            "idempotency_key",
            name=op.f("uq_embedding_runs_project_id_idempotency_key"),
        ),
    )
    op.create_index(
        "ix_embedding_runs_project_created", "embedding_runs", ["project_id", "created_at"]
    )
    op.create_index("ix_embedding_runs_project_status", "embedding_runs", ["project_id", "status"])

    op.create_table(
        "section_pattern_embeddings",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("section_pattern_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_run_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid()),
        sa.Column("dataset_version_id", sa.Uuid()),
        sa.Column("physical_collection", sa.String(240), nullable=False),
        sa.Column("embedding_provider", sa.String(32), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_model_digest", sa.String(128), nullable=False),
        sa.Column("serialization_schema_version", sa.Integer(), nullable=False),
        sa.Column("vector_name", sa.String(64), nullable=False),
        sa.Column("document_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("indexed_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'indexing', 'indexed', 'deleting', 'deleted', 'failed')",
            name=op.f("ck_section_pattern_embeddings_status_allowed"),
        ),
        sa.CheckConstraint(
            "attempts >= 0", name=op.f("ck_section_pattern_embeddings_attempts_nonnegative")
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["section_pattern_id"], ["section_patterns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["embedding_run_id"], ["embedding_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_section_pattern_embeddings")),
        sa.UniqueConstraint(
            "section_pattern_id",
            "physical_collection",
            name=op.f("uq_section_pattern_embeddings_section_pattern_id_physical_collection"),
        ),
    )
    op.create_index(
        "ix_section_pattern_embeddings_run_status",
        "section_pattern_embeddings",
        ["embedding_run_id", "status"],
    )
    op.create_index(
        "ix_section_pattern_embeddings_pattern",
        "section_pattern_embeddings",
        ["section_pattern_id", "status"],
    )
    op.create_index(
        "ix_section_pattern_embeddings_collection",
        "section_pattern_embeddings",
        ["physical_collection", "status"],
    )

    op.create_table(
        "embedding_index_failures",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_run_id", sa.Uuid(), nullable=False),
        sa.Column("section_pattern_id", sa.Uuid()),
        sa.Column("error_code", sa.String(100), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "attempt >= 1", name=op.f("ck_embedding_index_failures_attempt_positive")
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["embedding_run_id"], ["embedding_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["section_pattern_id"], ["section_patterns.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embedding_index_failures")),
    )
    op.create_index(
        "ix_embedding_index_failures_run_created",
        "embedding_index_failures",
        ["embedding_run_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("embedding_index_failures")
    op.drop_table("section_pattern_embeddings")
    op.drop_table("embedding_runs")
    op.drop_column("section_patterns", "legally_suppressed_at")
    op.drop_column("section_patterns", "retrieval_removed_at")
    op.drop_column("section_patterns", "retrieval_expires_at")
