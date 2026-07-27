"""Validated project API contracts."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from platform_api.models.common import PaginationParams
from platform_api.persistence.json import JsonValue

ProjectStatus = Literal["active", "archived", "draft"]
ProjectSort = Literal["created_at", "name", "updated_at"]
SortOrder = Literal["asc", "desc"]


class ProjectModel(BaseModel):
    """Strict base for project contracts."""

    model_config = ConfigDict(extra="forbid")


class ProjectCreateRequest(ProjectModel):
    """Create a user-owned project."""

    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2_000)
    default_language: str = Field(default="en", min_length=2, max_length=35)
    default_industry: str | None = Field(default=None, max_length=100)
    settings: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("name", "default_language")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value must not be blank.")
        return value

    @field_validator("description", "default_industry")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError("Slug must contain lowercase letters, numbers, and single hyphens.")
        return value


class ProjectUpdateRequest(ProjectModel):
    """Optimistically update mutable project fields."""

    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2_000)
    default_language: str | None = Field(default=None, min_length=2, max_length=35)
    default_industry: str | None = Field(default=None, max_length=100)
    settings: dict[str, JsonValue] | None = None

    @field_validator("name", "default_language")
    @classmethod
    def strip_required_when_present(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Value must not be blank.")
        return value

    @field_validator("description", "default_industry")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        return ProjectCreateRequest.validate_slug(value)

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if self.model_fields_set == {"version"}:
            raise ValueError("At least one project field must be supplied.")
        for required in ("name", "slug", "default_language", "settings"):
            if required in self.model_fields_set and getattr(self, required) is None:
                raise ValueError(f"{required} must not be null.")
        return self


class ProjectVersionRequest(ProjectModel):
    """Expected version for a lifecycle transition."""

    version: int = Field(ge=1)


class ProjectResponse(ProjectModel):
    """Complete safe project representation."""

    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID
    owner_id: UUID
    name: str
    slug: str
    description: str | None
    default_language: str
    default_industry: str | None
    status: ProjectStatus
    settings: dict[str, JsonValue]
    created_at: datetime
    updated_at: datetime
    version: int


class ProjectListParams(PaginationParams):
    """Bounded search, filter, and deterministic sorting parameters."""

    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None
    status: Annotated[ProjectStatus | None, Query()] = None
    sort_by: Annotated[ProjectSort, Query()] = "updated_at"
    sort_order: Annotated[SortOrder, Query()] = "desc"
