"""Crawler-owned transactional persistence and artifact service."""

from __future__ import annotations

import hashlib
import tempfile
import zlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

from platform_api.database import DatabaseManager
from platform_api.persistence.models import (
    CrawlPage,
    CrawlPolicyRecord,
    ScanCampaign,
    ScanFailure,
    ScanTarget,
)
from platform_clients.crawl_policy import CrawlPolicyConfig, RobotsPolicy
from platform_clients.object_storage import (
    Bucket,
    ObjectLocation,
    ObjectStorage,
    UploadRequest,
    scan_key,
)
from platform_clients.object_storage.models import RetentionMetadata
from sqlalchemy import func, select, update

from platform_crawler_worker.fingerprinting import (
    FINGERPRINT_ALGORITHM,
    FINGERPRINT_VERSION,
    FingerprintRecord,
    compute_page_fingerprints,
    group_fingerprints,
)
from platform_crawler_worker.models import (
    CrawlFailure,
    PageDiscovery,
    PageFingerprints,
    TargetCrawlConfiguration,
)


class CrawlConfigurationError(RuntimeError):
    pass


def _number(value: object, default: float) -> float:
    return float(value) if isinstance(value, (int, float, str)) else default


class CrawlRepository:
    def __init__(self, database: DatabaseManager, storage: ObjectStorage | None = None) -> None:
        self._database = database
        self._storage = storage

    async def load_configuration(
        self, campaign_id: UUID, target_id: UUID
    ) -> TargetCrawlConfiguration:
        async with self._database.session() as session:
            row = (
                await session.execute(
                    select(ScanCampaign, ScanTarget)
                    .join(ScanTarget, ScanTarget.campaign_id == ScanCampaign.id)
                    .where(ScanCampaign.id == campaign_id, ScanTarget.id == target_id)
                )
            ).one_or_none()
            if row is None:
                raise CrawlConfigurationError("scan target does not belong to campaign")
            campaign, target = row
            if not campaign.respect_robots_txt:
                raise CrawlConfigurationError("robots compliance is required")
            timeout = cast(dict[str, object], campaign.timeout_limits)
            retention = cast(dict[str, object], campaign.artifact_retention_policy)
            tracking = tuple(
                str(value) for value in cast(list[object], campaign.tracking_query_parameters)
            )
            return TargetCrawlConfiguration(
                campaign_id=campaign.id,
                project_id=campaign.project_id,
                target_id=target.id,
                seed_url=target.normalized_url,
                source_domain=target.source_domain,
                policy=CrawlPolicyConfig(
                    user_agent=campaign.crawler_user_agent,
                    maximum_depth=campaign.maximum_crawl_depth,
                    maximum_pages_per_domain=campaign.max_discovered_pages_per_domain,
                    include_patterns=tuple(cast(list[str], campaign.include_url_patterns)),
                    exclude_patterns=tuple(cast(list[str], campaign.exclude_url_patterns)),
                    tracking_parameters=frozenset(
                        value for value in tracking if not value.endswith("*")
                    ),
                    tracking_parameter_prefixes=tuple(
                        value[:-1] for value in tracking if value.endswith("*")
                    ),
                    query_parameter_ordering=campaign.query_parameter_ordering,
                    default_crawl_delay_seconds=campaign.crawl_delay_seconds,
                    token_bucket_capacity=campaign.per_domain_concurrency,
                ),
                allowed_content_types=frozenset(
                    str(value) for value in cast(list[object], campaign.allowed_content_types)
                ),
                per_domain_concurrency=campaign.per_domain_concurrency,
                overall_concurrency=campaign.overall_concurrency,
                connect_timeout_seconds=_number(timeout.get("connect_seconds"), 10),
                response_timeout_seconds=_number(timeout.get("response_seconds"), 30),
                campaign_timeout_seconds=int(_number(timeout.get("campaign_seconds"), 7_200)),
                store_raw_html=campaign.store_raw_html,
                retention_days=int(_number(retention.get("retention_days"), 30)),
            )

    async def persist_robots(
        self, configuration: TargetCrawlConfiguration, policy: RobotsPolicy
    ) -> UUID:
        async with self._database.transaction() as session:
            record = await session.scalar(
                select(CrawlPolicyRecord).where(
                    CrawlPolicyRecord.campaign_id == configuration.campaign_id,
                    CrawlPolicyRecord.target_id == configuration.target_id,
                )
            )
            values = {
                "source_domain": configuration.source_domain,
                "robots_url": policy.robots_url,
                "final_robots_url": policy.final_url,
                "fetch_status": policy.fetch_status.value,
                "fetched_at": policy.fetched_at,
                "content_sha256": policy.content_sha256,
                "crawler_user_agent": policy.user_agent,
                "crawl_delay_seconds": policy.crawl_delay_seconds,
                "redirect_count": policy.redirect_count,
                "sitemap_urls": list(policy.sitemaps),
                "effective_policy": {
                    "maximum_depth": configuration.policy.maximum_depth,
                    "maximum_pages_per_domain": configuration.policy.maximum_pages_per_domain,
                    "respect_robots_txt": True,
                    "policy_version": 2,
                    "query_parameter_ordering": configuration.policy.query_parameter_ordering,
                    "maximum_sitemap_depth": configuration.policy.maximum_sitemap_depth,
                    "maximum_sitemap_bytes": configuration.policy.maximum_sitemap_bytes,
                    "maximum_sitemap_urls": configuration.policy.maximum_sitemap_urls,
                },
            }
            if record is None:
                record = CrawlPolicyRecord(
                    campaign_id=configuration.campaign_id,
                    target_id=configuration.target_id,
                    **values,
                )
                session.add(record)
            else:
                for name, value in values.items():
                    setattr(record, name, value)
            await session.flush()
            return record.id

    async def persist_page(
        self,
        configuration: TargetCrawlConfiguration,
        policy_record_id: UUID,
        discovery: PageDiscovery,
    ) -> UUID:
        async with self._database.transaction() as session:
            parent_page_id = None
            if discovery.parent_url is not None:
                parent_page_id = await session.scalar(
                    select(CrawlPage.id).where(
                        CrawlPage.campaign_id == configuration.campaign_id,
                        CrawlPage.normalized_url == discovery.parent_url,
                    )
                )
            page = await session.scalar(
                select(CrawlPage).where(
                    CrawlPage.campaign_id == configuration.campaign_id,
                    CrawlPage.normalized_url == discovery.canonical_url,
                )
            )
            values = {
                "crawl_policy_record_id": policy_record_id,
                "parent_page_id": parent_page_id,
                "url": discovery.requested_url,
                "normalized_url": discovery.canonical_url,
                "final_url": discovery.final_url,
                "declared_canonical_url": discovery.declared_canonical_url,
                "source_domain": configuration.source_domain,
                "depth": discovery.depth,
                "status": "fetched",
                "robots_allowed": discovery.robots_allowed,
                "crawl_decision_code": "allowed",
                "crawl_policy_provenance": discovery.policy_provenance,
                "http_status": discovery.status_code,
                "content_type": discovery.content_type,
                "content_sha256": discovery.content_sha256,
                "title": discovery.title,
                "meta_description": discovery.meta_description,
                "language": discovery.language,
                "hreflang_links": [
                    {
                        "language": link.language,
                        "original_url": link.original_url,
                        "normalized_url": link.normalized_url,
                    }
                    for link in discovery.hreflang_links
                ],
                "last_modified_at": discovery.last_modified_at,
                "content_length": discovery.content_length,
                "discovery_source": discovery.discovery_source,
                "parent_url": discovery.parent_url,
                "fingerprint_algorithm": discovery.fingerprints.algorithm,
                "fingerprint_version": discovery.fingerprints.version,
                "normalized_url_sha256": discovery.fingerprints.normalized_url_sha256,
                "visible_text_sha256": discovery.fingerprints.visible_text_sha256,
                "dom_structure_sha256": discovery.fingerprints.dom_structure_sha256,
                "heading_sequence_sha256": discovery.fingerprints.heading_sequence_sha256,
                "link_structure_sha256": discovery.fingerprints.link_structure_sha256,
                "semantic_simhash": discovery.fingerprints.semantic_simhash,
                "dom_template_sha256": discovery.fingerprints.dom_template_sha256,
                "normalized_content_sha256": discovery.fingerprints.normalized_content_sha256,
                "normalized_text_length": discovery.fingerprints.normalized_text_length,
                "fingerprinted_at": discovery.fetched_at,
                "discovered_at": discovery.fetched_at,
                "fetched_at": discovery.fetched_at,
            }
            if page is None:
                page = CrawlPage(
                    campaign_id=configuration.campaign_id,
                    target_id=configuration.target_id,
                    **values,
                )
                session.add(page)
            else:
                for name, value in values.items():
                    setattr(page, name, value)
            await session.flush()
            page_id = page.id
        if configuration.store_raw_html and discovery.raw_html is not None:
            await self._store_html(configuration, page_id, discovery.raw_html)
        return page_id

    async def recalculate_deduplication(self, campaign_id: UUID) -> int:
        """Idempotently assign stable representatives for all fingerprinted campaign pages."""
        async with self._database.transaction() as session:
            await session.execute(
                select(func.pg_advisory_xact_lock(func.hashtext(str(campaign_id))))
            )
            await session.execute(
                update(CrawlPage)
                .where(CrawlPage.campaign_id == campaign_id)
                .values(
                    exact_duplicate_of_id=None,
                    near_duplicate_of_id=None,
                    template_representative_id=None,
                    exact_group_key=None,
                    near_group_key=None,
                    template_group_key=None,
                )
            )
            pages = tuple(
                (
                    await session.scalars(
                        select(CrawlPage)
                        .where(
                            CrawlPage.campaign_id == campaign_id,
                            CrawlPage.fingerprint_algorithm == FINGERPRINT_ALGORITHM,
                            CrawlPage.fingerprint_version == FINGERPRINT_VERSION,
                            CrawlPage.normalized_content_sha256.is_not(None),
                            CrawlPage.semantic_simhash.is_not(None),
                            CrawlPage.dom_template_sha256.is_not(None),
                            CrawlPage.normalized_text_length.is_not(None),
                        )
                        .order_by(CrawlPage.normalized_url.asc(), CrawlPage.id.asc())
                        .with_for_update()
                    )
                ).all()
            )
            records = tuple(
                FingerprintRecord(
                    id=page.id,
                    normalized_url=page.normalized_url,
                    normalized_content_sha256=cast(str, page.normalized_content_sha256),
                    semantic_simhash=cast(str, page.semantic_simhash),
                    dom_template_sha256=cast(str, page.dom_template_sha256),
                    normalized_text_length=cast(int, page.normalized_text_length),
                )
                for page in pages
            )
            by_id = {page.id: page for page in pages}
            for assignment in group_fingerprints(records):
                page = by_id[assignment.page_id]
                page.exact_duplicate_of_id = assignment.exact_duplicate_of_id
                page.near_duplicate_of_id = assignment.near_duplicate_of_id
                page.template_representative_id = assignment.template_representative_id
                page.exact_group_key = assignment.exact_group_key
                page.near_group_key = assignment.near_group_key
                page.template_group_key = assignment.template_group_key
            return len(pages)

    async def backfill_fingerprints(self, campaign_id: UUID) -> tuple[int, int]:
        """Recompute absent/outdated fingerprints from retained raw HTML, then regroup."""
        if self._storage is None:
            raise RuntimeError("object storage is required for fingerprint backfill")
        async with self._database.session() as session:
            candidates = tuple(
                (
                    await session.execute(
                        select(
                            CrawlPage.id,
                            CrawlPage.response_artifact_key,
                            CrawlPage.normalized_url,
                            CrawlPage.final_url,
                        ).where(
                            CrawlPage.campaign_id == campaign_id,
                            CrawlPage.response_artifact_key.is_not(None),
                            (CrawlPage.fingerprint_algorithm != FINGERPRINT_ALGORITHM)
                            | CrawlPage.fingerprint_algorithm.is_(None)
                            | (CrawlPage.fingerprint_version != FINGERPRINT_VERSION)
                            | CrawlPage.fingerprint_version.is_(None),
                        )
                    )
                ).all()
            )
        updated = 0
        for page_id, artifact_key, normalized_url, final_url in candidates:
            if not isinstance(artifact_key, str):
                continue
            body = await self._download_gzip_html(artifact_key)
            fingerprints = compute_page_fingerprints(
                body,
                normalized_url=str(normalized_url),
                response_url=str(final_url or normalized_url),
            )
            async with self._database.transaction() as session:
                page = await session.get(CrawlPage, page_id, with_for_update=True)
                if page is None or page.response_artifact_key != artifact_key:
                    continue
                self._assign_fingerprints(page, fingerprints, datetime.now(UTC))
                updated += 1
        grouped = await self.recalculate_deduplication(campaign_id)
        return updated, grouped

    async def _download_gzip_html(self, artifact_key: str) -> bytes:
        if self._storage is None:
            raise RuntimeError("object storage is required for fingerprint backfill")
        decompressor = zlib.decompressobj(wbits=31)
        output = bytearray()
        async for chunk in self._storage.stream_download(
            ObjectLocation(Bucket.SCAN_ARTIFACTS, artifact_key)
        ):
            output.extend(decompressor.decompress(chunk, 5 * 1_024 * 1_024 + 1 - len(output)))
            if len(output) > 5 * 1_024 * 1_024 or decompressor.unconsumed_tail:
                raise ValueError("raw HTML artifact exceeds fingerprint backfill limit")
        output.extend(decompressor.flush(5 * 1_024 * 1_024 + 1 - len(output)))
        if len(output) > 5 * 1_024 * 1_024 or not decompressor.eof or decompressor.unused_data:
            raise ValueError("raw HTML artifact is invalid or oversized")
        return bytes(output)

    @staticmethod
    def _assign_fingerprints(
        page: CrawlPage, fingerprints: PageFingerprints, fingerprinted_at: datetime
    ) -> None:
        page.fingerprint_algorithm = fingerprints.algorithm
        page.fingerprint_version = fingerprints.version
        page.normalized_url_sha256 = fingerprints.normalized_url_sha256
        page.visible_text_sha256 = fingerprints.visible_text_sha256
        page.dom_structure_sha256 = fingerprints.dom_structure_sha256
        page.heading_sequence_sha256 = fingerprints.heading_sequence_sha256
        page.link_structure_sha256 = fingerprints.link_structure_sha256
        page.semantic_simhash = fingerprints.semantic_simhash
        page.dom_template_sha256 = fingerprints.dom_template_sha256
        page.normalized_content_sha256 = fingerprints.normalized_content_sha256
        page.normalized_text_length = fingerprints.normalized_text_length
        page.content_sha256 = fingerprints.response_body_sha256
        page.fingerprinted_at = fingerprinted_at

    async def _store_html(
        self, configuration: TargetCrawlConfiguration, page_id: UUID, body: bytes
    ) -> None:
        if self._storage is None:
            raise RuntimeError("raw HTML storage is configured but object storage is unavailable")
        compressor = zlib.compressobj(level=6, method=zlib.DEFLATED, wbits=31)
        with tempfile.NamedTemporaryFile(prefix="aiwg-crawl-", suffix=".html.gz") as output:
            digest = hashlib.sha256()
            for offset in range(0, len(body), 64 * 1_024):
                compressed = compressor.compress(body[offset : offset + 64 * 1_024])
                if compressed:
                    output.write(compressed)
                    digest.update(compressed)
            final = compressor.flush()
            output.write(final)
            digest.update(final)
            output.flush()
            location = scan_key(configuration.target_id, page_id, "raw.html.gz")
            await self._storage.upload(
                location,
                _file_chunks(Path(output.name)),
                UploadRequest(
                    expected_sha256=digest.hexdigest(),
                    content_type="text/html",
                    content_encoding="gzip",
                    tags={"artifact": "raw-html", "target-id": str(configuration.target_id)},
                    retention=RetentionMetadata(
                        policy="scan-campaign",
                        retain_until=datetime.now(UTC)
                        + timedelta(days=configuration.retention_days),
                    ),
                ),
            )
        async with self._database.transaction() as session:
            page = await session.get(CrawlPage, page_id)
            if page is not None:
                page.response_artifact_key = location.key

    async def record_failure(
        self, configuration: TargetCrawlConfiguration, failure: CrawlFailure
    ) -> None:
        fingerprint = hashlib.sha256(
            f"{configuration.target_id}|{failure.code}|{failure.requested_url or ''}".encode()
        ).hexdigest()
        async with self._database.transaction() as session:
            existing = await session.scalar(
                select(ScanFailure.id).where(
                    ScanFailure.campaign_id == configuration.campaign_id,
                    ScanFailure.failure_key == fingerprint,
                )
            )
            if existing is None:
                session.add(
                    ScanFailure(
                        campaign_id=configuration.campaign_id,
                        target_id=configuration.target_id,
                        stage="crawl",
                        error_code=failure.code[:100],
                        message=failure.message[:1_000],
                        failure_key=fingerprint,
                        retryable=failure.retryable,
                        attempt=1,
                    )
                )

    async def mark_target(self, target_id: UUID, status: str) -> None:
        async with self._database.transaction() as session:
            target = await session.get(ScanTarget, target_id)
            if target is not None:
                target.status = status


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as source:
        while chunk := source.read(64 * 1_024):
            yield chunk
