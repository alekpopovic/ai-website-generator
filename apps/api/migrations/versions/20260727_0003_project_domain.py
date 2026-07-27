"""Complete the user-owned project domain.

Revision ID: 20260727_0003
Revises: 20260727_0002
Create Date: 2026-07-27 00:00:02+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260727_0003"
down_revision: str | None = "20260727_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add project identity, locale, industry, and ownership constraints."""
    op.drop_index("ix_projects_owner_user_id_updated_at", table_name="projects")
    op.drop_constraint("fk_projects_owner_user_id_users", "projects", type_="foreignkey")
    op.alter_column("projects", "owner_user_id", new_column_name="owner_id")
    op.create_foreign_key(
        "fk_projects_owner_id_users",
        "projects",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column("projects", sa.Column("slug", sa.String(length=100)))
    op.add_column("projects", sa.Column("default_language", sa.String(length=35)))
    op.add_column("projects", sa.Column("default_industry", sa.String(length=100)))
    op.execute(
        "UPDATE projects SET slug = 'project-' || replace(id::text, '-', ''), "
        "default_language = 'en'"
    )
    op.alter_column("projects", "slug", nullable=False)
    op.alter_column("projects", "default_language", nullable=False)
    op.create_index("ix_projects_owner_id_updated_at", "projects", ["owner_id", "updated_at"])
    op.create_unique_constraint("uq_projects_owner_id_slug", "projects", ["owner_id", "slug"])


def downgrade() -> None:
    """Restore the original project persistence stub."""
    op.drop_constraint("uq_projects_owner_id_slug", "projects", type_="unique")
    op.drop_index("ix_projects_owner_id_updated_at", table_name="projects")
    op.drop_column("projects", "default_industry")
    op.drop_column("projects", "default_language")
    op.drop_column("projects", "slug")
    op.drop_constraint("fk_projects_owner_id_users", "projects", type_="foreignkey")
    op.alter_column("projects", "owner_id", new_column_name="owner_user_id")
    op.create_foreign_key(
        "fk_projects_owner_user_id_users",
        "projects",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_projects_owner_user_id_updated_at",
        "projects",
        ["owner_user_id", "updated_at"],
    )
