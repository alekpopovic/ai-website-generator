"""Repository protocols and transaction-scoped SQLAlchemy implementations."""

from __future__ import annotations

from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from platform_api.persistence.base import utc_now
from platform_api.persistence.models import AuditLog, AuthActionToken, Project, RefreshToken, User
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


class AuthenticationRepository:
    """Authentication persistence operations inside one caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entity: User | RefreshToken | AuthActionToken) -> None:
        self._session.add(entity)

    async def flush(self) -> None:
        await self._session.flush()

    async def user_by_email(self, email: str) -> User | None:
        return cast(
            User | None, await self._session.scalar(select(User).where(User.email == email))
        )

    async def user_by_id(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def refresh_for_update(self, token_hash: str) -> RefreshToken | None:
        return cast(
            RefreshToken | None,
            await self._session.scalar(
                select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
            ),
        )

    async def action_for_update(self, *, token_hash: str, purpose: str) -> AuthActionToken | None:
        return cast(
            AuthActionToken | None,
            await self._session.scalar(
                select(AuthActionToken)
                .where(
                    AuthActionToken.token_hash == token_hash,
                    AuthActionToken.purpose == purpose,
                )
                .with_for_update()
            ),
        )

    async def revoke_family(self, family_id: UUID) -> None:
        now = utc_now()
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.status == "active")
            .values(status="revoked", revoked_at=now)
        )

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        now = utc_now()
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.status == "active")
            .values(status="revoked", revoked_at=now)
        )

    async def consume_pending_actions(self, *, user_id: UUID, purpose: str) -> None:
        await self._session.execute(
            update(AuthActionToken)
            .where(
                AuthActionToken.user_id == user_id,
                AuthActionToken.purpose == purpose,
                AuthActionToken.consumed_at.is_(None),
            )
            .values(consumed_at=utc_now())
        )


class ProjectRepository(SqlAlchemyRepository[Project]):
    """Project persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Project)

    async def flush(self) -> None:
        await self._session.flush()

    async def owned(
        self, project_id: UUID, owner_id: UUID, *, for_update: bool = False
    ) -> Project | None:
        statement = select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(Project | None, await self._session.scalar(statement))

    async def slug_exists(
        self, owner_id: UUID, slug: str, *, exclude_id: UUID | None = None
    ) -> bool:
        statement = select(Project.id).where(Project.owner_id == owner_id, Project.slug == slug)
        if exclude_id is not None:
            statement = statement.where(Project.id != exclude_id)
        return await self._session.scalar(statement) is not None

    async def owned_page(
        self,
        *,
        owner_id: UUID,
        limit: int,
        offset: int,
        search: str | None,
        status: str | None,
        sort_by: str,
        sort_order: str,
    ) -> Page[Project]:
        filters = [Project.owner_id == owner_id]
        if search:
            term = search.strip()
            filters.append(
                or_(
                    Project.name.icontains(term, autoescape=True),
                    Project.slug.icontains(term, autoescape=True),
                    Project.description.icontains(term, autoescape=True),
                )
            )
        if status is not None:
            filters.append(Project.status == status)
        statement: Select[tuple[Project]] = select(Project).where(*filters)
        sort_column = {
            "created_at": Project.created_at,
            "name": Project.name,
            "updated_at": Project.updated_at,
        }[sort_by]
        ordering = sort_column.asc() if sort_order == "asc" else sort_column.desc()
        statement = apply_pagination(
            statement.order_by(ordering, Project.id.asc()), limit=limit, offset=offset
        )
        items = tuple((await self._session.scalars(statement)).all())
        total = await self._session.scalar(
            select(func.count()).select_from(Project).where(*filters)
        )
        return Page(items=items, total=total or 0, limit=limit, offset=offset)


class SqlAlchemyAuditLogRepository(SqlAlchemyRepository[AuditLog]):
    """SQLAlchemy audit-log adapter."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AuditLog)
