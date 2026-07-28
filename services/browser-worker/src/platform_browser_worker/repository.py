"""PostgreSQL ownership, idempotency, artifact, and failure boundaries for browser scans."""

from __future__ import annotations

import hashlib
import json
import zlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from platform_api.artifacts.persistence import ScanArtifactRecordInput, record_scan_artifact
from platform_api.database import DatabaseManager
from platform_api.persistence.json import JsonValue
from platform_api.persistence.models import CrawlPage, PageScan, ScanCampaign, ScanFailure
from platform_clients.object_storage import (
    ArtifactAccessPolicy,
    ArtifactProvenanceStatus,
    ArtifactRetentionStatus,
    ObjectStorage,
    ScanArtifactKind,
    ScanObjectMetadata,
)
from platform_clients.object_storage.keys import scan_key
from platform_clients.object_storage.models import RetentionMetadata, StoredObject, UploadRequest
from sqlalchemy import func, select

from platform_browser_worker.models import (
    CAPTURE_SCHEMA_VERSION,
    BrowserCapture,
    BrowserCaptureLimits,
    BrowserFailureCode,
    BrowserScanConfiguration,
    BrowserScanError,
    BrowserViewport,
    PreparedPageScan,
    ViewportName,
)


@dataclass(frozen=True, slots=True)
class _ArtifactSpec:
    kind: ScanArtifactKind
    body: bytes
    content_type: str
    content_encoding: str | None
    label: str
    suffix: str
    access_policy: ArtifactAccessPolicy


class BrowserScanRepository:
    def __init__(self, database: DatabaseManager, storage: ObjectStorage) -> None:
        self._database = database
        self._storage = storage

    async def load_configuration(
        self, campaign_id: UUID, crawl_page_id: UUID
    ) -> BrowserScanConfiguration:
        async with self._database.session() as session:
            row = (
                await session.execute(
                    select(CrawlPage, ScanCampaign)
                    .join(ScanCampaign, ScanCampaign.id == CrawlPage.campaign_id)
                    .where(CrawlPage.id == crawl_page_id, CrawlPage.campaign_id == campaign_id)
                )
            ).one_or_none()
        if row is None:
            raise BrowserScanError(
                BrowserFailureCode.PAGE_NOT_ELIGIBLE,
                "The requested crawl page does not exist in the campaign.",
            )
        page, campaign = row
        if page.status != "fetched" or not page.representative_selected:
            raise BrowserScanError(
                BrowserFailureCode.PAGE_NOT_ELIGIBLE,
                "The crawl page is not an eligible representative.",
            )
        desktop = _viewport(campaign.desktop_viewport, ViewportName.DESKTOP, 1440, 1000)
        mobile = _viewport(campaign.mobile_viewport, ViewportName.MOBILE, 390, 844)
        timeouts = _object_dict(campaign.timeout_limits)
        retention = _object_dict(campaign.artifact_retention_policy)
        return BrowserScanConfiguration(
            campaign_id=campaign.id,
            project_id=campaign.project_id,
            target_id=page.target_id,
            crawl_page_id=page.id,
            url=page.normalized_url,
            source_content_sha256=page.content_sha256,
            raw_response_artifact_key=page.response_artifact_key,
            retention_days=_bounded_int(
                retention.get("retention_days"), 30, minimum=1, maximum=3650
            ),
            legal_hold=retention.get("legal_hold") is True,
            viewports=(desktop, mobile),
            limits=BrowserCaptureLimits(
                navigation_timeout_seconds=_bounded_float(
                    timeouts.get("browser_page_seconds"), 45, minimum=5, maximum=300
                ),
                total_timeout_seconds=min(
                    300.0,
                    max(
                        60.0,
                        _bounded_float(
                            timeouts.get("browser_page_seconds"),
                            45,
                            minimum=5,
                            maximum=300,
                        )
                        + 15,
                    ),
                ),
            ),
        )

    async def prepare(
        self, configuration: BrowserScanConfiguration, viewport: BrowserViewport
    ) -> PreparedPageScan:
        configuration_hash = configuration.configuration_hash(viewport)
        async with self._database.transaction() as session:
            await session.execute(
                select(
                    func.pg_advisory_xact_lock(
                        func.hashtext(f"{configuration.crawl_page_id}:{viewport.name.value}")
                    )
                )
            )
            scan = await session.scalar(
                select(PageScan)
                .where(
                    PageScan.crawl_page_id == configuration.crawl_page_id,
                    PageScan.viewport == viewport.name.value,
                    PageScan.configuration_hash == configuration_hash,
                )
                .with_for_update()
            )
            if scan is not None and scan.status == "succeeded":
                return PreparedPageScan(
                    scan.id, viewport, configuration_hash, True, scan.created_at
                )
            if scan is None:
                next_attempt = (
                    await session.scalar(
                        select(func.coalesce(func.max(PageScan.attempt), 0) + 1).where(
                            PageScan.crawl_page_id == configuration.crawl_page_id,
                            PageScan.viewport == viewport.name.value,
                        )
                    )
                ) or 1
                scan = PageScan(
                    id=uuid4(),
                    campaign_id=configuration.campaign_id,
                    crawl_page_id=configuration.crawl_page_id,
                    viewport=viewport.name.value,
                    viewport_width=viewport.width,
                    viewport_height=viewport.height,
                    attempt=int(next_attempt),
                    status="rendering",
                    configuration_hash=configuration_hash,
                    capture_schema_version=CAPTURE_SCHEMA_VERSION,
                    artifact_checksums={},
                    response_metadata={},
                    console_errors=[],
                    page_errors=[],
                    failed_requests=[],
                    external_host_manifest=[],
                    full_page_truncated=False,
                    started_at=datetime.now(UTC),
                )
                session.add(scan)
            else:
                scan.status = "rendering"
                scan.started_at = datetime.now(UTC)
                scan.completed_at = None
            await session.flush()
            return PreparedPageScan(scan.id, viewport, configuration_hash, False, scan.created_at)

    async def complete(
        self,
        configuration: BrowserScanConfiguration,
        prepared: PreparedPageScan,
        capture: BrowserCapture,
    ) -> None:
        scan_timestamp = prepared.scan_timestamp
        retention = RetentionMetadata(
            policy="legal-hold" if configuration.legal_hold else "scan-campaign",
            retain_until=None
            if configuration.legal_hold
            else scan_timestamp + timedelta(days=configuration.retention_days),
        )
        retention_status = (
            ArtifactRetentionStatus.LEGAL_HOLD
            if configuration.legal_hold
            else ArtifactRetentionStatus.ACTIVE
        )
        scanner_version = (
            f"playwright/{capture.browser_version};capture/{CAPTURE_SCHEMA_VERSION};"
            f"extractor/{capture.semantic_snapshot.extractor_version}"
        )[:200]
        semantic_snapshot = capture.semantic_snapshot.canonical_bytes()
        full_screenshot_kind = (
            ScanArtifactKind.DESKTOP_SCREENSHOT
            if prepared.viewport.name is ViewportName.DESKTOP
            else ScanArtifactKind.MOBILE_SCREENSHOT
        )
        artifacts = (
            _ArtifactSpec(
                full_screenshot_kind,
                capture.full_page_screenshot,
                "image/png",
                None,
                f"{prepared.viewport.name.value}-full-page",
                "png",
                ArtifactAccessPolicy.SAFE_SCREENSHOT,
            ),
            _ArtifactSpec(
                ScanArtifactKind.VIEWPORT_SCREENSHOT,
                capture.viewport_screenshot,
                "image/png",
                None,
                f"{prepared.viewport.name.value}-viewport",
                "png",
                ArtifactAccessPolicy.SAFE_SCREENSHOT,
            ),
            _ArtifactSpec(
                ScanArtifactKind.RENDERED_HTML,
                _gzip(capture.rendered_html.encode("utf-8")),
                "text/html",
                "gzip",
                "rendered-html",
                "html.gz",
                ArtifactAccessPolicy.RESTRICTED_RAW,
            ),
            _ArtifactSpec(
                ScanArtifactKind.SEMANTIC_SNAPSHOT,
                _gzip(semantic_snapshot),
                "application/json",
                "gzip",
                "semantic-snapshot",
                "json.gz",
                ArtifactAccessPolicy.PROJECT_MEMBER,
            ),
            _ArtifactSpec(
                ScanArtifactKind.EXTRACTED_NODES,
                _gzip_json(
                    {
                        "extractor_version": capture.semantic_snapshot.extractor_version,
                        "nodes": [
                            node.model_dump(mode="json", exclude_none=True)
                            for node in capture.semantic_snapshot.nodes
                        ],
                    }
                ),
                "application/json",
                "gzip",
                "extracted-nodes",
                "json.gz",
                ArtifactAccessPolicy.PROJECT_MEMBER,
            ),
            _ArtifactSpec(
                ScanArtifactKind.STYLE_SUMMARY,
                _gzip_json(
                    {
                        "extractor_version": capture.semantic_snapshot.extractor_version,
                        "style_frequencies": capture.semantic_snapshot.style_frequencies.model_dump(
                            mode="json"
                        ),
                        "design_tokens": [
                            token.model_dump(mode="json")
                            for token in capture.semantic_snapshot.design_tokens
                        ],
                        "summary": capture.semantic_snapshot.summary.model_dump(mode="json"),
                    }
                ),
                "application/json",
                "gzip",
                "style-summary",
                "json.gz",
                ArtifactAccessPolicy.PROJECT_MEMBER,
            ),
            _ArtifactSpec(
                ScanArtifactKind.NETWORK_MANIFEST,
                _gzip_json(
                    {
                        "final_url": capture.final_url,
                        "response_metadata": capture.response_metadata,
                        "failed_requests": capture.failed_requests,
                        "external_hosts": capture.external_hosts,
                    }
                ),
                "application/json",
                "gzip",
                "network-manifest",
                "json.gz",
                ArtifactAccessPolicy.PROJECT_MEMBER,
            ),
            _ArtifactSpec(
                ScanArtifactKind.CONSOLE_DIAGNOSTICS,
                _gzip_json(
                    {
                        "console_errors": capture.console_errors,
                        "page_errors": capture.page_errors,
                    }
                ),
                "application/json",
                "gzip",
                "console-diagnostics",
                "json.gz",
                ArtifactAccessPolicy.PROJECT_MEMBER,
            ),
        )
        stored: dict[ScanArtifactKind, tuple[StoredObject, ArtifactAccessPolicy]] = {}
        try:
            for artifact in artifacts:
                digest = hashlib.sha256(artifact.body).hexdigest()
                location = scan_key(
                    configuration.target_id,
                    prepared.id,
                    f"{artifact.label}-{digest[:16]}.{artifact.suffix}",
                )
                result = await self._storage.upload(
                    location,
                    _bytes(artifact.body),
                    UploadRequest(
                        expected_sha256=digest,
                        content_type=artifact.content_type,
                        content_encoding=artifact.content_encoding,
                        tags={
                            "artifact": artifact.kind.value,
                            "viewport": prepared.viewport.name.value,
                            "source-website": str(configuration.target_id),
                            "campaign": str(configuration.campaign_id),
                            "provenance": ArtifactProvenanceStatus.AUTHORIZED.value,
                        },
                        metadata=ScanObjectMetadata(
                            source_url=configuration.url,
                            final_url=capture.final_url,
                            scan_timestamp=scan_timestamp,
                            scanner_version=scanner_version,
                            viewport=prepared.viewport.name.value,
                            content_type=artifact.content_type,
                            source_website_id=configuration.target_id,
                            campaign_id=configuration.campaign_id,
                            provenance_status=ArtifactProvenanceStatus.AUTHORIZED,
                        ).as_object_metadata(),
                        retention=retention,
                    ),
                )
                stored[artifact.kind] = (result, artifact.access_policy)
            manifest_spec = _ArtifactSpec(
                ScanArtifactKind.SCAN_METADATA_MANIFEST,
                _gzip(
                    _manifest_bytes(
                        capture,
                        prepared,
                        stored,
                        configuration=configuration,
                        scanner_version=scanner_version,
                        retention_status=retention_status,
                    )
                ),
                "application/json",
                "gzip",
                "scan-metadata-manifest",
                "json.gz",
                ArtifactAccessPolicy.PROJECT_MEMBER,
            )
            manifest_digest = hashlib.sha256(manifest_spec.body).hexdigest()
            manifest_result = await self._storage.upload(
                scan_key(
                    configuration.target_id,
                    prepared.id,
                    f"{manifest_spec.label}-{manifest_digest[:16]}.{manifest_spec.suffix}",
                ),
                _bytes(manifest_spec.body),
                UploadRequest(
                    expected_sha256=manifest_digest,
                    content_type=manifest_spec.content_type,
                    content_encoding=manifest_spec.content_encoding,
                    tags={
                        "artifact": manifest_spec.kind.value,
                        "viewport": prepared.viewport.name.value,
                        "source-website": str(configuration.target_id),
                        "campaign": str(configuration.campaign_id),
                        "provenance": ArtifactProvenanceStatus.AUTHORIZED.value,
                    },
                    metadata=ScanObjectMetadata(
                        source_url=configuration.url,
                        final_url=capture.final_url,
                        scan_timestamp=scan_timestamp,
                        scanner_version=scanner_version,
                        viewport=prepared.viewport.name.value,
                        content_type=manifest_spec.content_type,
                        source_website_id=configuration.target_id,
                        campaign_id=configuration.campaign_id,
                        provenance_status=ArtifactProvenanceStatus.AUTHORIZED,
                    ).as_object_metadata(),
                    retention=retention,
                ),
            )
            stored[manifest_spec.kind] = (manifest_result, manifest_spec.access_policy)
        except Exception as error:
            raise BrowserScanError(
                BrowserFailureCode.ARTIFACT_PERSISTENCE_FAILED,
                "Browser capture artifacts could not be persisted.",
                retryable=True,
            ) from error
        async with self._database.transaction() as session:
            scan = await session.get(PageScan, prepared.id, with_for_update=True)
            if scan is None or scan.configuration_hash != prepared.configuration_hash:
                raise BrowserScanError(
                    BrowserFailureCode.ARTIFACT_PERSISTENCE_FAILED,
                    "Browser scan state changed before artifacts were committed.",
                    retryable=True,
                )
            scan.status = "succeeded"
            scan.screenshot_artifact_key = stored[full_screenshot_kind][0].location.key
            scan.viewport_screenshot_artifact_key = stored[ScanArtifactKind.VIEWPORT_SCREENSHOT][
                0
            ].location.key
            scan.rendered_html_artifact_key = stored[ScanArtifactKind.RENDERED_HTML][0].location.key
            scan.analysis_artifact_key = stored[ScanArtifactKind.SCAN_METADATA_MANIFEST][
                0
            ].location.key
            scan.semantic_snapshot_artifact_key = stored[ScanArtifactKind.SEMANTIC_SNAPSHOT][
                0
            ].location.key
            scan.artifact_checksums = cast(
                JsonValue, {kind.value: item.sha256 for kind, (item, _) in stored.items()}
            )
            scan.response_metadata = cast(JsonValue, capture.response_metadata)
            scan.browser_version = capture.browser_version[:64]
            scan.final_url = capture.final_url[:2_048]
            scan.page_title = capture.title[:500]
            scan.meta_description = capture.meta_description
            scan.canonical_url = capture.canonical_url
            scan.language = capture.language
            scan.visible_text_summary = capture.visible_text_summary
            scan.extractor_version = capture.semantic_snapshot.extractor_version[:64]
            scan.extracted_node_count = len(capture.semantic_snapshot.nodes)
            scan.extraction_payload_bytes = len(semantic_snapshot)
            scan.extraction_truncated = capture.semantic_snapshot.truncated
            scan.semantic_snapshot_summary = cast(
                JsonValue, capture.semantic_snapshot.summary.model_dump(mode="json")
            )
            scan.console_errors = list(capture.console_errors)
            scan.page_errors = list(capture.page_errors)
            scan.failed_requests = cast(JsonValue, list(capture.failed_requests))
            scan.external_host_manifest = list(capture.external_hosts)
            scan.document_width = capture.dimensions.width
            scan.document_height = capture.dimensions.height
            scan.screenshot_width = capture.dimensions.screenshot_width
            scan.screenshot_height = capture.dimensions.screenshot_height
            scan.full_page_truncated = capture.dimensions.full_page_truncated
            scan.completed_at = datetime.now(UTC)
            for kind, (item, access_policy) in stored.items():
                await record_scan_artifact(
                    session,
                    ScanArtifactRecordInput(
                        project_id=configuration.project_id,
                        campaign_id=configuration.campaign_id,
                        source_website_id=configuration.target_id,
                        crawl_page_id=configuration.crawl_page_id,
                        page_scan_id=prepared.id,
                        artifact_type=kind,
                        stored=item,
                        source_url=configuration.url,
                        final_url=capture.final_url,
                        scan_timestamp=scan_timestamp,
                        scanner_version=scanner_version,
                        viewport=prepared.viewport.name.value,
                        provenance_status=ArtifactProvenanceStatus.AUTHORIZED,
                        access_policy=access_policy,
                        retention_status=retention_status,
                    ),
                )

    async def fail(
        self,
        configuration: BrowserScanConfiguration,
        prepared: PreparedPageScan | None,
        error: BrowserScanError,
    ) -> None:
        failure_key = hashlib.sha256(
            (
                f"{configuration.crawl_page_id}|"
                f"{prepared.configuration_hash if prepared else 'configuration'}|{error.code.value}"
            ).encode()
        ).hexdigest()
        async with self._database.transaction() as session:
            if prepared is not None:
                scan = await session.get(PageScan, prepared.id, with_for_update=True)
                if scan is not None and scan.status != "succeeded":
                    scan.status = "failed"
                    scan.completed_at = datetime.now(UTC)
            failure = await session.scalar(
                select(ScanFailure).where(
                    ScanFailure.campaign_id == configuration.campaign_id,
                    ScanFailure.failure_key == failure_key,
                )
            )
            if failure is None:
                session.add(
                    ScanFailure(
                        campaign_id=configuration.campaign_id,
                        target_id=configuration.target_id,
                        crawl_page_id=configuration.crawl_page_id,
                        page_scan_id=prepared.id if prepared else None,
                        stage="browser",
                        error_code=error.code.value,
                        message=error.message[:1_000],
                        failure_key=failure_key,
                        retryable=error.retryable,
                        attempt=1,
                    )
                )
            else:
                failure.attempt += 1
                failure.retryable = error.retryable
                failure.resolved_at = None

    async def cancel(
        self, configuration: BrowserScanConfiguration, prepared: PreparedPageScan | None
    ) -> None:
        if prepared is None:
            return
        async with self._database.transaction() as session:
            scan = await session.get(PageScan, prepared.id, with_for_update=True)
            if scan is not None and scan.status == "rendering":
                scan.status = "cancelled"
                scan.completed_at = datetime.now(UTC)


def _viewport(
    raw: JsonValue,
    name: ViewportName,
    default_width: int,
    default_height: int,
) -> BrowserViewport:
    values = _object_dict(raw)
    return BrowserViewport(
        name=name,
        width=_bounded_int(values.get("width"), default_width, minimum=240, maximum=3840),
        height=_bounded_int(values.get("height"), default_height, minimum=240, maximum=2160),
        is_mobile=name is ViewportName.MOBILE,
    )


def _object_dict(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _bounded_int(value: object, default: int, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return min(maximum, max(minimum, int(value)))


def _bounded_float(value: object, default: float, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return min(maximum, max(minimum, float(value)))


def _gzip(body: bytes) -> bytes:
    compressor = zlib.compressobj(level=6, method=zlib.DEFLATED, wbits=31)
    return compressor.compress(body) + compressor.flush()


def _manifest_bytes(
    capture: BrowserCapture,
    prepared: PreparedPageScan,
    stored: dict[ScanArtifactKind, tuple[StoredObject, ArtifactAccessPolicy]],
    *,
    configuration: BrowserScanConfiguration,
    scanner_version: str,
    retention_status: ArtifactRetentionStatus,
) -> bytes:
    value = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "configuration_hash": prepared.configuration_hash,
        "project_id": str(configuration.project_id),
        "campaign_id": str(configuration.campaign_id),
        "source_website_id": str(configuration.target_id),
        "crawl_page_id": str(configuration.crawl_page_id),
        "page_scan_id": str(prepared.id),
        "source_url": configuration.url,
        "viewport": {
            "name": prepared.viewport.name.value,
            "width": prepared.viewport.width,
            "height": prepared.viewport.height,
        },
        "final_url": capture.final_url,
        "scan_timestamp": prepared.scan_timestamp.astimezone(UTC).isoformat(),
        "scanner_version": scanner_version,
        "provenance_status": ArtifactProvenanceStatus.AUTHORIZED.value,
        "retention_status": retention_status.value,
        "response_metadata": capture.response_metadata,
        "title": capture.title,
        "meta_description": capture.meta_description,
        "canonical_url": capture.canonical_url,
        "language": capture.language,
        "visible_text_summary": capture.visible_text_summary,
        "semantic_extraction": {
            "extractor_version": capture.semantic_snapshot.extractor_version,
            "node_count": len(capture.semantic_snapshot.nodes),
            "payload_bytes": len(capture.semantic_snapshot.canonical_bytes()),
            "truncated": capture.semantic_snapshot.truncated,
            "summary": capture.semantic_snapshot.summary.model_dump(mode="json"),
        },
        "console_errors": capture.console_errors,
        "page_errors": capture.page_errors,
        "failed_requests": capture.failed_requests,
        "external_hosts": capture.external_hosts,
        "document_dimensions": {
            "width": capture.dimensions.width,
            "height": capture.dimensions.height,
            "screenshot_width": capture.dimensions.screenshot_width,
            "screenshot_height": capture.dimensions.screenshot_height,
            "full_page_truncated": capture.dimensions.full_page_truncated,
        },
        "browser_version": capture.browser_version,
        "raw_response_artifact_key": configuration.raw_response_artifact_key,
        "artifacts": [
            {
                "artifact_type": kind.value,
                "bucket": item.location.bucket.value,
                "object_key": item.location.key,
                "sha256": item.sha256,
                "size_bytes": item.size,
                "content_type": item.content_type,
                "content_encoding": item.content_encoding,
            }
            for kind, (item, _) in sorted(stored.items(), key=lambda value: value[0].value)
        ],
    }
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")


def _gzip_json(value: object) -> bytes:
    return _gzip(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


async def _bytes(body: bytes) -> AsyncIterator[bytes]:
    for offset in range(0, len(body), 64 * 1_024):
        yield body[offset : offset + 64 * 1_024]
