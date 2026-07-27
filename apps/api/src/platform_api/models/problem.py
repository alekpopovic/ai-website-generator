"""RFC 7807-style error response contracts."""

from __future__ import annotations

from typing import Any

from pydantic import AnyUrl, BaseModel, ConfigDict, Field


class InvalidParameter(BaseModel):
    """Sanitized request-validation failure detail."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    location: str
    reason: str


class ProblemDetail(BaseModel):
    """Problem Details response compatible with RFC 7807 and RFC 9457 clients."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    type_: AnyUrl | str = Field(alias="type", default="about:blank")
    title: str
    status: int = Field(ge=400, le=599)
    detail: str | None = None
    instance: str | None = None
    code: str
    request_id: str
    invalid_parameters: list[InvalidParameter] | None = None
    extensions: dict[str, Any] | None = None
