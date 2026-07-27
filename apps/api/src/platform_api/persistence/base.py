"""Declarative base, naming conventions, and reusable ORM mixins."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import DateTime, MetaData, Uuid, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utc_now() -> datetime:
    """Return an aware UTC timestamp for application-created values."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative metadata root imported by application code and Alembic."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """Use application-generated UUIDs so IDs exist before a flush."""

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


class TimestampMixin:
    """Provide database-backed creation and modification timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
        onupdate=utc_now,
        server_onupdate=func.now(),
    )


class OptimisticVersionMixin:
    """Enable SQLAlchemy optimistic concurrency checks for editable records."""

    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default=text("1"))

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, object]:
        """Register the shared version column with SQLAlchemy's mapper."""
        return {"version_id_col": cls.version}
