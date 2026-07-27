"""Generic API and pagination response models."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field


class StrictResponseModel(BaseModel):
    """Base class for immutable response contracts with forbidden extra fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ResponseMeta(StrictResponseModel):
    """Metadata common to envelope responses."""

    request_id: str | None = None


class ApiResponse[DataT](StrictResponseModel):
    """Typed response envelope for versioned API routes."""

    data: DataT
    meta: ResponseMeta = Field(default_factory=ResponseMeta)


class PaginationParams(BaseModel):
    """Validated offset pagination query values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    offset: Annotated[int, Query(ge=0)] = 0
    limit: Annotated[int, Query(ge=1, le=100)] = 20


class PaginationMeta(StrictResponseModel):
    """Stable pagination metadata independent of domain resources."""

    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
    has_more: bool

    @classmethod
    def from_params(cls, params: PaginationParams, total: int) -> PaginationMeta:
        """Create metadata without allowing arithmetic to escape the primitive."""
        return cls(
            offset=params.offset,
            limit=params.limit,
            total=total,
            has_more=params.offset + params.limit < total,
        )


class PageResponse[DataT](StrictResponseModel):
    """Typed collection response with offset pagination."""

    items: list[DataT]
    pagination: PaginationMeta
    meta: ResponseMeta = Field(default_factory=ResponseMeta)
