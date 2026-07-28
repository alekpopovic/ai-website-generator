"""Public metadata contracts for private scan artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ArtifactType = Literal[
    "raw_response_html",
    "rendered_html",
    "desktop_screenshot",
    "mobile_screenshot",
    "viewport_screenshot",
    "semantic_snapshot",
    "extracted_nodes",
    "style_summary",
    "network_manifest",
    "console_diagnostics",
    "scan_metadata_manifest",
]
RetentionStatus = Literal["active", "pending_deletion", "legal_hold", "expired", "deleted"]
ProvenanceStatus = Literal["authorized", "restricted", "removal_pending", "removed"]


class ArtifactModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScanArtifactResponse(ArtifactModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID
    campaign_id: UUID
    crawl_page_id: UUID
    page_scan_id: UUID | None
    artifact_type: ArtifactType
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    content_type: str
    content_encoding: str | None
    scanner_version: str
    viewport: Literal["desktop", "mobile"] | None
    provenance_status: ProvenanceStatus
    retention_status: RetentionStatus
    retain_until: datetime | None
    scan_timestamp: datetime
    created_at: datetime


class PresignedArtifactReadResponse(ArtifactModel):
    artifact_id: UUID
    url: str
    expires_seconds: int = Field(ge=60, le=900)


class ArtifactRemovalRequest(ArtifactModel):
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
