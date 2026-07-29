"""Strict dataset API and reproducible selection contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from platform_api.persistence.json import JsonValue

DatasetStatus = Literal["active", "archived"]
DatasetVersionStatus = Literal["draft", "sealed"]
DatasetBuildStatus = Literal["queued", "running", "cancelling", "cancelled", "failed", "succeeded"]
DatasetItemType = Literal["section_pattern", "full_site_spec"]
DatasetSplit = Literal["train", "validation", "test"]
ProvenanceRequirement = Literal["authorized", "restricted"]


class DatasetModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SelectionPolicy(DatasetModel):
    source_campaign_filters: tuple[UUID, ...] = Field(default=(), max_length=100)
    category_filters: tuple[str, ...] = Field(default=(), max_length=100)
    language_filters: tuple[str, ...] = Field(default=(), max_length=50)
    item_types: tuple[DatasetItemType, ...] = ("section_pattern",)
    minimum_confidence: float = Field(default=0.7, ge=0, le=1)
    require_approved: bool = True
    provenance_requirements: tuple[ProvenanceRequirement, ...] = ("authorized",)

    @field_validator("source_campaign_filters")
    @classmethod
    def unique_values[T](cls, values: tuple[T, ...]) -> tuple[T, ...]:
        if len(values) != len(set(values)):
            raise ValueError("Selection lists must be unique.")
        return values

    @field_validator("item_types", "provenance_requirements")
    @classmethod
    def nonempty_unique_values[T](cls, values: tuple[T, ...]) -> tuple[T, ...]:
        if not values or len(values) != len(set(values)):
            raise ValueError("Selection lists must be non-empty and unique.")
        return values

    @field_validator("category_filters", "language_filters")
    @classmethod
    def normalize_filters(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip().casefold() for value in values)
        if any(not value or len(value) > 64 for value in normalized):
            raise ValueError("Filter values must contain at most 64 characters.")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Filter values must be unique.")
        return normalized


class DatasetCreateRequest(SelectionPolicy):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    purpose: str = Field(min_length=1, max_length=500)

    @field_validator("name", "purpose")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Value must not be blank.")
        return normalized


class DatasetUpdateRequest(DatasetModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    purpose: str | None = Field(default=None, min_length=1, max_length=500)
    status: DatasetStatus | None = None
    source_campaign_filters: tuple[UUID, ...] | None = Field(default=None, max_length=100)
    category_filters: tuple[str, ...] | None = Field(default=None, max_length=100)
    language_filters: tuple[str, ...] | None = Field(default=None, max_length=50)
    item_types: tuple[DatasetItemType, ...] | None = None
    minimum_confidence: float | None = Field(default=None, ge=0, le=1)
    require_approved: bool | None = None
    provenance_requirements: tuple[ProvenanceRequirement, ...] | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        values = self.model_dump(exclude={"version"}, exclude_none=True)
        if not values:
            raise ValueError("At least one dataset field must be changed.")
        policy_values = {key: values[key] for key in SelectionPolicy.model_fields if key in values}
        if policy_values:
            defaults = SelectionPolicy().model_dump()
            SelectionPolicy.model_validate({**defaults, **policy_values})
        return self


class DatasetResponse(SelectionPolicy):
    id: UUID
    project_id: UUID
    name: str
    description: str | None
    purpose: str
    status: DatasetStatus
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime
    version: int


class DatasetVersionCreateRequest(DatasetModel):
    selection_policy: SelectionPolicy | None = None
    schema_version: int = Field(default=1, ge=1, le=100)
    embedding_version: str | None = Field(default=None, min_length=1, max_length=240)


class DatasetVersionUpdateRequest(DatasetModel):
    version: int = Field(ge=1)
    selection_policy: SelectionPolicy | None = None
    schema_version: int | None = Field(default=None, ge=1, le=100)
    embedding_version: str | None = Field(default=None, min_length=1, max_length=240)

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if (
            self.selection_policy is None
            and self.schema_version is None
            and self.embedding_version is None
        ):
            raise ValueError("At least one draft version field must be changed.")
        return self


class DatasetQualityPolicy(DatasetModel):
    max_domain_share: float = Field(default=0.6, gt=0, le=1)
    minimum_category_count: int = Field(default=2, ge=1, le=100)
    max_repeated_template_share: float = Field(default=0.25, ge=0, le=1)
    required_section_types: tuple[str, ...] = Field(default=(), max_length=32)
    maximum_serialized_text_chars: int = Field(default=20_000, ge=256, le=100_000)

    @field_validator("required_section_types")
    @classmethod
    def normalize_section_types(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip().casefold() for value in values)
        if any(not value or len(value) > 32 for value in normalized):
            raise ValueError("Required section types must contain at most 32 characters.")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Required section types must be unique.")
        return normalized


class DatasetBuildStartRequest(DatasetModel):
    idempotency_key: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    quality_policy: DatasetQualityPolicy = Field(default_factory=DatasetQualityPolicy)
    enqueue_missing_embeddings: bool = False


class DatasetBuildRetryRequest(DatasetModel):
    idempotency_key: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )


class DatasetBuildCancelRequest(DatasetModel):
    version: int = Field(ge=1)


class DatasetVersionResponse(DatasetModel):
    id: UUID
    dataset_id: UUID
    status: DatasetVersionStatus
    version_number: int
    selection_config: SelectionPolicy
    selection_manifest: dict[str, JsonValue]
    manifest_sha256: str | None
    schema_version: int
    embedding_version: str | None
    analyzer_versions: tuple[str, ...]
    statistics: dict[str, JsonValue]
    created_by_user_id: UUID | None
    sealed_by_user_id: UUID | None
    sealed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class DatasetItemResponse(DatasetModel):
    id: UUID
    dataset_version_id: UUID
    item_type: DatasetItemType
    source_record_id: UUID
    source_campaign_id: UUID
    source_website_id: UUID
    source_page_id: UUID | None
    source_domain: str
    split: DatasetSplit
    category: str
    language: str
    confidence: float
    schema_version: int
    analyzer_version: str
    content_sha256: str
    availability_status: Literal["active", "removed", "suppressed"]
    created_at: datetime


class DatasetQualityReportResponse(DatasetModel):
    id: UUID
    dataset_version_id: UUID
    status: Literal["passed", "failed"]
    item_count: int
    statistics: dict[str, JsonValue]
    findings: tuple[dict[str, JsonValue], ...]
    report_version: int
    created_at: datetime


class DatasetVersionDetailResponse(DatasetModel):
    dataset: DatasetResponse
    version: DatasetVersionResponse
    quality_report: DatasetQualityReportResponse | None


class DatasetBuildResponse(DatasetModel):
    id: UUID
    project_id: UUID
    dataset_id: UUID
    dataset_version_id: UUID
    requested_by_user_id: UUID | None
    status: DatasetBuildStatus
    stage: str
    idempotency_key: str
    quality_policy: DatasetQualityPolicy
    enqueue_missing_embeddings: bool
    excluded_counts: dict[str, JsonValue]
    workflow_id: str | None
    workflow_run_id: str | None
    workflow_attempt: int
    failure_code: str | None
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int
