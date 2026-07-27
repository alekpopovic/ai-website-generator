"""Initial PostgreSQL-owned application records."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from platform_api.persistence.base import (
    Base,
    OptimisticVersionMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from platform_api.persistence.json import JsonValue, SafeJSONB


class User(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Locally authenticated platform identity."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="status_allowed"),
        Index("ix_users_email", "email", unique=True),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(back_populates="user")
    projects: Mapped[list[Project]] = relationship(back_populates="owner")


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """Hashed refresh-token lifecycle record; plaintext tokens are never persisted."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'revoked', 'expired')", name="status_allowed"),
        Index("ix_refresh_tokens_user_id_status", "user_id", "status"),
        UniqueConstraint("token_hash"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    family_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_metadata: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class Project(UUIDPrimaryKeyMixin, TimestampMixin, OptimisticVersionMixin, Base):
    """User-editable website-generation project metadata."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'archived')", name="status_allowed"),
        Index("ix_projects_owner_user_id_updated_at", "owner_user_id", "updated_at"),
    )

    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2_000))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    settings: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    owner: Mapped[User] = relationship(back_populates="projects")


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """Append-only security and business decision record."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[UUID | None]
    request_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class JobEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only durable event projection for asynchronous jobs."""

    __tablename__ = "job_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="status_allowed",
        ),
        CheckConstraint("sequence >= 0", name="sequence_non_negative"),
        UniqueConstraint("job_id", "sequence"),
        Index("ix_job_events_project_id_created_at", "project_id", "created_at"),
    )

    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    job_id: Mapped[UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[JsonValue] = mapped_column(
        SafeJSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
