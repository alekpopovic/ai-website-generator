"""Artifact metadata persistence boundary kept separate from object bytes."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from platform_clients.object_storage.models import ObjectLocation, RetentionMetadata


@dataclass(frozen=True, slots=True)
class ArtifactMetadataRecord:
    """Relational metadata required for authorization, lineage, and retention."""

    artifact_id: UUID
    owner_id: UUID
    location: ObjectLocation
    sha256: str
    size: int
    content_type: str
    retention: RetentionMetadata | None
    created_at: datetime


class ArtifactMetadataRepository(Protocol):
    """Persistence interface implemented inside an explicit database transaction."""

    async def record(self, metadata: ArtifactMetadataRecord) -> None: ...

    async def get(self, artifact_id: UUID) -> ArtifactMetadataRecord | None: ...

    async def remove(self, artifact_id: UUID) -> None: ...


class InMemoryArtifactMetadataRepository:
    """Deterministic metadata repository for unit tests."""

    def __init__(self) -> None:
        self._records: dict[UUID, ArtifactMetadataRecord] = {}

    async def record(self, metadata: ArtifactMetadataRecord) -> None:
        existing = self._records.get(metadata.artifact_id)
        if existing is not None and existing != metadata:
            raise ValueError("artifact metadata ID already contains a different record")
        self._records[metadata.artifact_id] = metadata

    async def get(self, artifact_id: UUID) -> ArtifactMetadataRecord | None:
        return self._records.get(artifact_id)

    async def remove(self, artifact_id: UUID) -> None:
        self._records.pop(artifact_id, None)
