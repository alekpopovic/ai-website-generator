"""Typed offset-pagination helpers shared by SQLAlchemy repositories."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.sql import Select


@dataclass(frozen=True, slots=True)
class Page[EntityT]:
    """One stable page plus the total matching record count."""

    items: tuple[EntityT, ...]
    total: int
    limit: int
    offset: int


def apply_pagination[EntityT](
    statement: Select[tuple[EntityT]], *, limit: int, offset: int
) -> Select[tuple[EntityT]]:
    """Apply validated offset pagination to a typed select statement."""
    if limit < 1:
        raise ValueError("limit must be positive")
    if offset < 0:
        raise ValueError("offset must not be negative")
    return statement.limit(limit).offset(offset)
