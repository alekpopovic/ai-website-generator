"""Repository protocols and transaction-scoped SQLAlchemy implementations."""

from __future__ import annotations

from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from platform_api.persistence.models import AuditLog, Project, User
from platform_api.persistence.pagination import Page, apply_pagination


class Repository[EntityT: DeclarativeBase](Protocol):
    """Minimal persistence interface; callers own transaction boundaries."""

    async def get(self, entity_id: UUID) -> EntityT | None: ...

    def add(self, entity: EntityT) -> None: ...

    async def page(self, *, limit: int, offset: int) -> Page[EntityT]: ...


class AuditLogRepository(Protocol):
    """Append-only interface consumed by the audit service."""

    def add(self, entry: AuditLog) -> None: ...


class SqlAlchemyRepository[EntityT: DeclarativeBase]:
    """Generic SQLAlchemy repository bound to one caller-owned session."""

    def __init__(self, session: AsyncSession, model: type[EntityT]) -> None:
        self._session = session
        self._model = model

    async def get(self, entity_id: UUID) -> EntityT | None:
        """Return an entity by primary key without opening a transaction."""
        return await self._session.get(self._model, entity_id)

    def add(self, entity: EntityT) -> None:
        """Stage an entity; the transaction owner decides whether to commit."""
        self._session.add(entity)

    async def page(self, *, limit: int, offset: int) -> Page[EntityT]:
        """Return an ID-ordered page and its independent total count."""
        statement = apply_pagination(
            select(self._model).order_by(self._model.__table__.c.id), limit=limit, offset=offset
        )
        items = tuple((await self._session.scalars(statement)).all())
        total = await self._session.scalar(select(func.count()).select_from(self._model))
        return Page(items=items, total=total or 0, limit=limit, offset=offset)


class UserRepository(SqlAlchemyRepository[User]):
    """User persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def by_email(self, email: str) -> User | None:
        """Look up a normalized email address."""
        return cast(
            User | None, await self._session.scalar(select(User).where(User.email == email))
        )


class ProjectRepository(SqlAlchemyRepository[Project]):
    """Project persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Project)


class SqlAlchemyAuditLogRepository(SqlAlchemyRepository[AuditLog]):
    """SQLAlchemy audit-log adapter."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AuditLog)
