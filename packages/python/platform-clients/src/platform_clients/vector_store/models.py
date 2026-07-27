"""Strict vector collection, point, filter, and result contracts."""

from __future__ import annotations

import hashlib
import math
import re
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

DESIGN_PATTERN_SERIALIZATION_SCHEMA_VERSION = 1
DESIGN_PATTERN_VECTOR_NAME = "design-pattern"
_COLLECTION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,239}$")
_SAFE_TEXT = re.compile(r"^[^<>\x00-\x08\x0b\x0c\x0e-\x1f]*$")
_URL = re.compile(r"(?i)(?:https?://|www\.)")


class ProvenanceStatus(StrEnum):
    """Retrieval eligibility derived from authoritative provenance records."""

    PENDING = "pending"
    VERIFIED = "verified"
    RESTRICTED = "restricted"
    REMOVED = "removed"


class CollectionIdentity(BaseModel):
    """Immutable embedding and serialization identity for one physical collection."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    embedding_provider: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,31}$")
    embedding_model: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/:-]*$",
    )
    embedding_model_digest: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    serialization_schema_version: int = Field(
        default=DESIGN_PATTERN_SERIALIZATION_SCHEMA_VERSION,
        ge=1,
        le=65_535,
    )
    vector_name: str = Field(
        default=DESIGN_PATTERN_VECTOR_NAME,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
    )

    def physical_name(self, alias: str) -> str:
        """Build a stable bounded name incorporating every version dimension."""
        if _COLLECTION_NAME.fullmatch(alias) is None:
            raise ValueError("collection alias is invalid")
        model_slug = re.sub(r"[^a-z0-9]+", "-", self.embedding_model.casefold()).strip("-")
        identity = "\x1f".join(
            (
                self.embedding_provider,
                self.embedding_model,
                self.embedding_model_digest,
                str(self.serialization_schema_version),
                self.vector_name,
            )
        )
        identity_hash = hashlib.sha256(identity.encode()).hexdigest()[:16]
        prefix = f"{alias}--{self.embedding_provider}--{model_slug[:48]}"
        suffix = f"--{self.embedding_model_digest[:32]}--s{self.serialization_schema_version}--{identity_hash}"
        return f"{prefix[: 240 - len(suffix)]}{suffix}"


class DesignPatternPayload(BaseModel):
    """Allowlisted abstract retrieval metadata; arbitrary scraped fields are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    project_id: UUID
    dataset_id: UUID
    dataset_version_id: UUID
    source_website_id: UUID
    source_page_id: UUID
    section_pattern_id: UUID
    source_domain: str = Field(min_length=1, max_length=253)
    category: str = Field(min_length=1, max_length=80)
    page_type: str = Field(min_length=1, max_length=80)
    section_type: str = Field(min_length=1, max_length=80)
    layout: str = Field(min_length=1, max_length=120)
    style_tags: tuple[str, ...] = Field(default=(), max_length=32)
    language: str = Field(pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
    confidence: float = Field(ge=0, le=1)
    approved: bool
    provenance_status: ProvenanceStatus

    @field_validator("source_domain")
    @classmethod
    def normalize_source_domain(cls, value: str) -> str:
        domain = value.rstrip(".").casefold()
        if ":" in domain or "/" in domain or "@" in domain or not domain:
            raise ValueError("source_domain must be a hostname without a port or URL")
        try:
            normalized = domain.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise ValueError("source_domain is invalid") from error
        if any(not label or len(label) > 63 for label in normalized.split(".")):
            raise ValueError("source_domain is invalid")
        return normalized

    @field_validator("category", "page_type", "section_type", "layout")
    @classmethod
    def reject_unstructured_metadata(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or _SAFE_TEXT.fullmatch(normalized) is None or _URL.search(normalized):
            raise ValueError("design-pattern metadata must be bounded abstract text")
        return normalized

    @field_validator("style_tags")
    @classmethod
    def validate_style_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.strip().casefold() for value in values)
        if any(
            not value
            or len(value) > 48
            or _SAFE_TEXT.fullmatch(value) is None
            or _URL.search(value)
            for value in normalized
        ):
            raise ValueError("style tags must be bounded abstract labels")
        if len(normalized) != len(set(normalized)):
            raise ValueError("style tags must be unique")
        return normalized


class VectorPoint(BaseModel):
    """One idempotent design-pattern point with exactly one named dense vector."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    abstract_pattern_text: str = Field(min_length=1, max_length=2_048)
    payload: DesignPatternPayload
    vector: tuple[float, ...] = Field(min_length=1, max_length=65_536)
    abstract_only: Literal[True] = True

    @property
    def point_id(self) -> UUID:
        """Use the stable section-pattern ID for replacement-safe upserts."""
        return self.payload.section_pattern_id

    @field_validator("abstract_pattern_text")
    @classmethod
    def validate_abstract_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if (
            not normalized
            or _SAFE_TEXT.fullmatch(normalized) is None
            or _URL.search(normalized)
            or len(normalized) > 2_048
        ):
            raise ValueError("only bounded URL-free abstract pattern text may be stored")
        return normalized

    @field_validator("vector")
    @classmethod
    def validate_dense_vector(cls, vector: tuple[float, ...]) -> tuple[float, ...]:
        if any(not math.isfinite(value) for value in vector):
            raise ValueError("dense vector values must be finite")
        return vector


class PayloadFilter(BaseModel):
    """Typed metadata filters; tenant/project scope is always explicit."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    project_id: UUID
    dataset_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    dataset_version_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    source_domains: tuple[str, ...] = Field(default=(), max_length=100)
    source_website_ids: tuple[UUID, ...] = Field(default=(), max_length=100)
    categories: tuple[str, ...] = Field(default=(), max_length=50)
    page_types: tuple[str, ...] = Field(default=(), max_length=50)
    section_types: tuple[str, ...] = Field(default=(), max_length=50)
    layouts: tuple[str, ...] = Field(default=(), max_length=50)
    style_tags: tuple[str, ...] = Field(default=(), max_length=50)
    languages: tuple[str, ...] = Field(default=(), max_length=50)
    minimum_confidence: float | None = Field(default=None, ge=0, le=1)
    approved: bool = True
    provenance_statuses: tuple[ProvenanceStatus, ...] = (ProvenanceStatus.VERIFIED,)

    @field_validator("source_domains")
    @classmethod
    def normalize_domains(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(DesignPatternPayload.normalize_source_domain(value) for value in values)


class DiversityField(StrEnum):
    SOURCE_DOMAIN = "source_domain"
    SOURCE_WEBSITE = "source_website_id"


class DiversityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    field: DiversityField = DiversityField.SOURCE_DOMAIN
    maximum_per_source: int = Field(default=1, ge=1, le=20)
    oversample_factor: int = Field(default=4, ge=1, le=20)


class VectorQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    vector: tuple[float, ...] = Field(min_length=1, max_length=65_536)
    filters: PayloadFilter
    limit: int = Field(default=10, ge=1, le=100)
    score_threshold: float | None = None
    diversity: DiversityPolicy | None = None

    @field_validator("vector")
    @classmethod
    def validate_query_vector(cls, vector: tuple[float, ...]) -> tuple[float, ...]:
        if any(not math.isfinite(value) for value in vector):
            raise ValueError("query vector values must be finite")
        return vector


class VectorMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    point_id: UUID
    score: float
    abstract_pattern_text: str
    payload: DesignPatternPayload


class CollectionStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    alias: str
    physical_collection: str | None
    status: str
    ready: bool
    vector_name: str
    dimensions: int | None = Field(default=None, ge=1, le=65_536)
    points_count: int = Field(default=0, ge=0)
    indexed_vectors_count: int = Field(default=0, ge=0)
    identity: CollectionIdentity | None = None


class VectorStoreHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    available: bool
    detail: str | None = None


class VectorStoreReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ready: bool
    alias: str
    expected_collection: str
    active_collection: str | None
    dimensions_match: bool
    identity_match: bool
    detail: str | None = None


class ScrollPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    points: tuple[tuple[UUID, str, DesignPatternPayload], ...]
    next_offset: str | int | None = None
