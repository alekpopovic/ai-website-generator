"""Compact worker records without raw source content."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from platform_clients.vector_store.models import (
    CollectionIdentity,
    DesignPatternPayload,
    ProvenanceStatus,
)
from platform_schemas import SectionPattern, StyleTag


@dataclass(frozen=True, slots=True)
class EmbeddingRunRecord:
    id: UUID
    project_id: UUID
    kind: str
    status: str
    batch_size: int
    promote_alias: bool
    collection_alias: str
    serialization_schema_version: int
    vector_name: str
    dataset_id: UUID | None = None
    dataset_version_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class PatternForEmbedding:
    id: UUID
    project_id: UUID
    source_website_id: UUID
    source_page_id: UUID
    source_domain: str
    category: str
    page_type: str
    section_type: str
    layout: str
    style_tags: tuple[StyleTag, ...]
    language: str
    confidence: float
    pattern: SectionPattern
    retrieval_document: str
    retrieval_expires_at: datetime | None
    retrieval_removed_at: datetime | None
    legally_suppressed_at: datetime | None
    approval_state: str
    provenance_state: str
    current_document_sha256: str | None
    current_status: str | None
    current_dataset_id: UUID | None = None
    current_dataset_version_id: UUID | None = None
    dataset_id: UUID | None = None
    dataset_version_id: UUID | None = None

    def eligible(self, now: datetime) -> bool:
        return (
            self.approval_state == "approved"
            and self.provenance_state == "authorized"
            and self.retrieval_removed_at is None
            and self.legally_suppressed_at is None
            and (self.retrieval_expires_at is None or self.retrieval_expires_at > now)
        )

    def payload(self) -> DesignPatternPayload:
        return DesignPatternPayload(
            project_id=self.project_id,
            dataset_id=self.dataset_id,
            dataset_version_id=self.dataset_version_id,
            source_website_id=self.source_website_id,
            source_page_id=self.source_page_id,
            section_pattern_id=self.id,
            source_domain=self.source_domain,
            category=self.category,
            page_type=self.page_type,
            section_type=self.section_type,
            layout=self.layout,
            style_tags=tuple(tag.value for tag in self.style_tags),
            language=self.language,
            confidence=self.confidence,
            approved=True,
            provenance_status=ProvenanceStatus.VERIFIED,
        )


@dataclass(frozen=True, slots=True)
class RemovalRecord:
    section_pattern_id: UUID
    identity: CollectionIdentity
    physical_collection: str


@dataclass(frozen=True, slots=True)
class IndexOutcome:
    run_id: UUID
    indexed: int
    deleted: int
    skipped: int
    promoted: bool
