"""Transactional typed records for checksum-verified immutable scan objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from platform_clients.object_storage.models import StoredObject
from platform_clients.object_storage.scan_artifacts import (
    ArtifactAccessPolicy,
    ArtifactProvenanceStatus,
    ArtifactRetentionStatus,
    ScanArtifactKind,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_api.persistence.models import ScanArtifact


class ArtifactRecordConflict(RuntimeError):
    """The immutable object key is already bound to different relational metadata."""


@dataclass(frozen=True, slots=True)
class ScanArtifactRecordInput:
    project_id: UUID
    campaign_id: UUID
    source_website_id: UUID
    crawl_page_id: UUID
    page_scan_id: UUID | None
    artifact_type: ScanArtifactKind
    stored: StoredObject
    source_url: str
    final_url: str
    scan_timestamp: datetime
    scanner_version: str
    viewport: str | None
    provenance_status: ArtifactProvenanceStatus
    access_policy: ArtifactAccessPolicy
    retention_status: ArtifactRetentionStatus


async def record_scan_artifact(
    session: AsyncSession, value: ScanArtifactRecordInput
) -> ScanArtifact:
    """Insert one immutable artifact record or verify an identical retry."""

    existing = await session.scalar(
        select(ScanArtifact)
        .where(
            ScanArtifact.bucket == value.stored.location.bucket.value,
            ScanArtifact.object_key == value.stored.location.key,
        )
        .with_for_update()
    )
    expected = _immutable_values(value)
    if existing is not None:
        if any(getattr(existing, name) != field_value for name, field_value in expected.items()):
            raise ArtifactRecordConflict(
                "immutable scan object key is bound to different artifact metadata"
            )
        return existing
    artifact = ScanArtifact(
        **expected,
        retention_status=value.retention_status.value,
    )
    session.add(artifact)
    await session.flush()
    return artifact


def _immutable_values(value: ScanArtifactRecordInput) -> dict[str, object]:
    retention = value.stored.retention
    return {
        "project_id": value.project_id,
        "campaign_id": value.campaign_id,
        "source_website_id": value.source_website_id,
        "crawl_page_id": value.crawl_page_id,
        "page_scan_id": value.page_scan_id,
        "artifact_type": value.artifact_type.value,
        "bucket": value.stored.location.bucket.value,
        "object_key": value.stored.location.key,
        "sha256": value.stored.sha256,
        "size_bytes": value.stored.size,
        "content_type": value.stored.content_type,
        "content_encoding": value.stored.content_encoding,
        "source_url": value.source_url,
        "final_url": value.final_url,
        "scan_timestamp": value.scan_timestamp,
        "scanner_version": value.scanner_version,
        "viewport": value.viewport,
        "provenance_status": value.provenance_status.value,
        "access_policy": value.access_policy.value,
        "retention_policy": retention.policy if retention is not None else "none",
        "retain_until": retention.retain_until if retention is not None else None,
    }
