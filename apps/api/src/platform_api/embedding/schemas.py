"""Embedding run command and progress API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EmbeddingRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["incremental", "reindex"] = "incremental"
    idempotency_key: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    batch_size: int = Field(default=64, ge=1, le=256)
    promote_alias: bool = False

    @model_validator(mode="after")
    def validate_promotion(self) -> EmbeddingRunCreateRequest:
        if self.promote_alias and self.kind != "reindex":
            raise ValueError("alias promotion is allowed only for a full reindex")
        return self


class EmbeddingRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    kind: Literal["incremental", "reindex"]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    batch_size: int
    promote_alias: bool
    collection_alias: str
    physical_collection: str | None
    embedding_provider: str | None
    embedding_model: str | None
    embedding_model_digest: str | None
    serialization_schema_version: int
    vector_name: str
    dimensions: int | None
    total_patterns: int
    processed_patterns: int
    indexed_patterns: int
    deleted_patterns: int
    failed_patterns: int
    workflow_id: str | None
    failure_code: str | None
    started_at: datetime | None
    completed_at: datetime | None
    alias_switched_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class EmbeddingFailureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    embedding_run_id: UUID
    section_pattern_id: UUID | None
    error_code: str
    attempt: int
    retryable: bool
    created_at: datetime
