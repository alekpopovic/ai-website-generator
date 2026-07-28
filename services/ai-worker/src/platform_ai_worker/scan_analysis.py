"""Load private scan artifacts, analyze them, and atomically persist profiles."""

from __future__ import annotations

import json
import zlib
from typing import Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from platform_api.analysis.repository import AnalysisRepository
from platform_api.analysis.schemas import AnalysisRunInput, PageAnalysisPersistenceInput
from platform_api.analysis.service import AnalysisProfileService
from platform_api.database import DatabaseManager
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.models import (
    CrawlPage,
    PageProfile,
    PageScan,
    ScanArtifact,
    ScanCampaign,
)
from platform_clients.object_storage import Bucket, ObjectLocation, ObjectStorage
from platform_schemas import PageType
from platform_workflows.commands import ScanPageInput
from sqlalchemy import select

from platform_ai_worker.page_analysis_models import (
    AnalyzerStrategy,
    PageAnalysisRequest,
    PageAnalysisSource,
    ViewportMetadata,
)
from platform_ai_worker.page_analyzer import PageAnalyzer

_MAX_JSON = 2 * 1024 * 1024
_MAX_IMAGE = 10 * 1024 * 1024


class PersistedScanPageAnalyzer:
    def __init__(
        self, database: DatabaseManager, storage: ObjectStorage, analyzer: PageAnalyzer
    ) -> None:
        self._database = database
        self._storage = storage
        self._analyzer = analyzer

    async def analyze_and_persist(self, command: ScanPageInput) -> str:
        page_id = UUID(command.crawl_page_id)
        campaign_id = UUID(command.campaign_id)
        async with self._database.session() as session:
            page = await session.scalar(
                select(CrawlPage).where(
                    CrawlPage.id == page_id, CrawlPage.campaign_id == campaign_id
                )
            )
            project_id = await session.scalar(
                select(ScanCampaign.project_id).where(ScanCampaign.id == campaign_id)
            )
            scans = tuple(
                (
                    await session.scalars(
                        select(PageScan).where(
                            PageScan.crawl_page_id == page_id, PageScan.status == "succeeded"
                        )
                    )
                ).all()
            )
        if page is None or project_id is None:
            raise LookupError("crawl page was not found")
        desktop = next((item for item in scans if item.viewport == "desktop"), None)
        mobile = next((item for item in scans if item.viewport == "mobile"), None)
        if desktop is None or desktop.configuration_hash is None:
            raise LookupError("desktop browser scan is not ready")
        run_id = uuid5(NAMESPACE_URL, f"scan-analysis:{page_id}:{desktop.configuration_hash}")
        async with self._database.session() as session:
            existing = await session.scalar(
                select(PageProfile.id).where(PageProfile.analysis_run_id == run_id)
            )
        if existing is not None:
            return str(existing)

        snapshot = await self._json_artifact(desktop.id, "semantic_snapshot")
        style = await self._json_artifact(desktop.id, "style_summary")
        desktop_image = await self._download(desktop.screenshot_artifact_key, _MAX_IMAGE)
        mobile_image = (
            await self._download(mobile.screenshot_artifact_key, _MAX_IMAGE)
            if mobile is not None
            else None
        )
        request = PageAnalysisRequest(
            source=PageAnalysisSource(
                project_id=project_id,
                campaign_id=campaign_id,
                source_website_id=page.target_id,
                source_page_id=page.id,
                desktop_page_scan_id=desktop.id,
                mobile_page_scan_id=mobile.id if mobile is not None else None,
                page_type=PageType(page.page_type or "unknown"),
                language=page.language,
                scanner_version=f"playwright/{desktop.browser_version or 'unknown'}",
                extractor_version=desktop.extractor_version or "unknown",
                desktop_viewport=_viewport(desktop),
                mobile_viewport=_viewport(mobile) if mobile is not None else None,
            ),
            compact_semantic_snapshot=snapshot,
            deterministic_style_summary=style,
            structural_section_candidates=tuple(
                cast(list[dict[str, object]], snapshot.get("sections", []))
            ),
            desktop_screenshot=desktop_image,
            mobile_screenshot=mobile_image,
        )
        result = await self._analyzer.analyze(request)
        strategy: Literal["dspy", "direct-structured-fallback"] = (
            "dspy"
            if result.metadata.strategy is AnalyzerStrategy.DSPY
            else "direct-structured-fallback"
        )
        value = PageAnalysisPersistenceInput(
            project_id=request.source.project_id,
            campaign_id=campaign_id,
            source_website_id=page.target_id,
            source_page_id=page.id,
            run=AnalysisRunInput(
                id=run_id,
                prompt_version=result.metadata.prompt_version,
                analyzer_version=result.metadata.analyzer_version,
                strategy=strategy,
                model_name=result.metadata.model_name,
                model_digest=result.metadata.model_digest,
                schema_version=result.metadata.schema_version,
                latency_ms=round(result.metadata.latency_ms),
                attempts=result.metadata.attempts,
                used_fallback=result.metadata.fallback_reason is not None,
            ),
            profile=result.payload.page_profile,
            design_tokens=result.payload.design_tokens,
            language=page.language or "en",
        )
        async with self._database.transaction() as session:
            repository = AnalysisRepository(session)
            response = await AnalysisProfileService(
                repository,
                AuditLogService(repository),
            ).persist_page(value)
            return str(response.id)

    async def _json_artifact(self, page_scan_id: UUID, kind: str) -> dict[str, object]:
        async with self._database.session() as session:
            artifact = await session.scalar(
                select(ScanArtifact).where(
                    ScanArtifact.page_scan_id == page_scan_id,
                    ScanArtifact.artifact_type == kind,
                )
            )
        if artifact is None:
            raise LookupError(f"{kind} artifact is not ready")
        compressed = await self._download(artifact.object_key, _MAX_JSON)
        body = zlib.decompress(compressed, wbits=31, bufsize=_MAX_JSON)
        if len(body) > _MAX_JSON:
            raise ValueError("analysis JSON artifact exceeds limit")
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("analysis JSON artifact must be an object")
        return cast(dict[str, object], value)

    async def _download(self, key: str | None, maximum: int) -> bytes:
        if key is None:
            raise LookupError("required scan artifact key is missing")
        body = bytearray()
        async for chunk in self._storage.stream_download(
            ObjectLocation(Bucket.SCAN_ARTIFACTS, key)
        ):
            body.extend(chunk)
            if len(body) > maximum:
                raise ValueError("scan artifact exceeds analysis limit")
        return bytes(body)


def _viewport(scan: PageScan) -> ViewportMetadata:
    return ViewportMetadata(
        width=scan.viewport_width,
        height=scan.viewport_height,
        document_height=scan.document_height or scan.viewport_height,
    )
