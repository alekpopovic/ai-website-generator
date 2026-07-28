"""Typed scan-artifact vocabulary and bounded object metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import quote
from uuid import UUID


class ScanArtifactKind(StrEnum):
    RAW_RESPONSE_HTML = "raw_response_html"
    RENDERED_HTML = "rendered_html"
    DESKTOP_SCREENSHOT = "desktop_screenshot"
    MOBILE_SCREENSHOT = "mobile_screenshot"
    VIEWPORT_SCREENSHOT = "viewport_screenshot"
    SEMANTIC_SNAPSHOT = "semantic_snapshot"
    EXTRACTED_NODES = "extracted_nodes"
    STYLE_SUMMARY = "style_summary"
    NETWORK_MANIFEST = "network_manifest"
    CONSOLE_DIAGNOSTICS = "console_diagnostics"
    SCAN_METADATA_MANIFEST = "scan_metadata_manifest"


class ArtifactAccessPolicy(StrEnum):
    RESTRICTED_RAW = "restricted_raw"
    PROJECT_MEMBER = "project_member"
    SAFE_SCREENSHOT = "safe_screenshot"


class ArtifactRetentionStatus(StrEnum):
    ACTIVE = "active"
    PENDING_DELETION = "pending_deletion"
    LEGAL_HOLD = "legal_hold"
    EXPIRED = "expired"
    DELETED = "deleted"


class ArtifactProvenanceStatus(StrEnum):
    AUTHORIZED = "authorized"
    RESTRICTED = "restricted"
    REMOVAL_PENDING = "removal_pending"
    REMOVED = "removed"


SENSITIVE_ARTIFACT_KINDS = frozenset(
    {ScanArtifactKind.RAW_RESPONSE_HTML, ScanArtifactKind.RENDERED_HTML}
)
SCREENSHOT_ARTIFACT_KINDS = frozenset(
    {
        ScanArtifactKind.DESKTOP_SCREENSHOT,
        ScanArtifactKind.MOBILE_SCREENSHOT,
        ScanArtifactKind.VIEWPORT_SCREENSHOT,
    }
)


@dataclass(frozen=True, slots=True)
class ScanObjectMetadata:
    """Required provenance metadata mirrored into each immutable S3 object."""

    source_url: str
    final_url: str
    scan_timestamp: datetime
    scanner_version: str
    viewport: str
    content_type: str
    source_website_id: UUID
    campaign_id: UUID
    provenance_status: ArtifactProvenanceStatus

    def __post_init__(self) -> None:
        if self.scan_timestamp.utcoffset() is None:
            raise ValueError("scan timestamp must be timezone-aware")
        if self.viewport not in {"desktop", "mobile", "none"}:
            raise ValueError("artifact viewport is invalid")
        if not self.scanner_version or len(self.scanner_version) > 200:
            raise ValueError("scanner version must be bounded")
        if not self.content_type or len(self.content_type) > 255:
            raise ValueError("artifact content type must be bounded")
        for value in (self.source_url, self.final_url):
            if not value.startswith(("http://", "https://")) or len(value) > 2_048:
                raise ValueError("artifact source URLs must be bounded HTTP(S) URLs")

    def as_object_metadata(self) -> dict[str, str]:
        return {
            "source-url": _ascii_url(self.source_url),
            "final-url": _ascii_url(self.final_url),
            "scan-timestamp": self.scan_timestamp.astimezone(UTC).isoformat(),
            "scanner-version": self.scanner_version,
            "viewport": self.viewport,
            "artifact-content-type": self.content_type,
            "source-website": str(self.source_website_id),
            "campaign": str(self.campaign_id),
            "provenance-status": self.provenance_status.value,
        }


def _ascii_url(value: str) -> str:
    return quote(value, safe=":/?#[]@!$&'()*+,;=-._~%")
