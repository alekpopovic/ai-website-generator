"""Add first-party authentication lifecycle state.

Revision ID: 20260727_0002
Revises: 20260727_0001
Create Date: 2026-07-27 00:00:01+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260727_0002"
down_revision: str | None = "20260727_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add verification, reset, and refresh-token rotation state."""
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True)))
    op.add_column("refresh_tokens", sa.Column("replaced_by_token_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_refresh_tokens_replaced_by_token_id_refresh_tokens",
        "refresh_tokens",
        "refresh_tokens",
        ["replaced_by_token_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "auth_action_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('email_verification', 'password_reset')", name="purpose_allowed"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_auth_action_tokens_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_action_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_auth_action_tokens_token_hash"),
    )
    op.create_index(
        "ix_auth_action_tokens_user_id_purpose",
        "auth_action_tokens",
        ["user_id", "purpose"],
    )


def downgrade() -> None:
    """Remove authentication lifecycle state."""
    op.drop_index("ix_auth_action_tokens_user_id_purpose", table_name="auth_action_tokens")
    op.drop_table("auth_action_tokens")
    op.drop_constraint(
        "fk_refresh_tokens_replaced_by_token_id_refresh_tokens",
        "refresh_tokens",
        type_="foreignkey",
    )
    op.drop_column("refresh_tokens", "replaced_by_token_id")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "email_verified_at")
