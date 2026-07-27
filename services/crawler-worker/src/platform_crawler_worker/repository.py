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
from platform_clients.object_storage import ObjectStorage, UploadRequest, scan_key
from platform_clients.object_storage.models import RetentionMetadata
from sqlalchemy import select

from platform_crawler_worker.models import CrawlFailure, PageDiscovery, TargetCrawlConfiguration


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
                    "policy_version": 1,
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
                "content_length": discovery.content_length,
                "discovery_source": discovery.discovery_source,
                "parent_url": discovery.parent_url,
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
