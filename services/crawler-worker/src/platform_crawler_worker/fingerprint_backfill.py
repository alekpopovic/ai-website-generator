"""Explicit idempotent duplicate-group backfill for persisted page fingerprints."""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from platform_api.config import get_settings
from platform_api.database import DatabaseManager
from platform_api.persistence.models import CrawlPage
from platform_clients.object_storage import StorageConfig
from platform_clients.object_storage.models import StorageProvider
from platform_clients.object_storage.s3 import S3ObjectStorage
from sqlalchemy import distinct, select

from platform_crawler_worker.repository import CrawlRepository


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", action="append", type=UUID, default=[])
    return parser.parse_args()


async def backfill(campaign_ids: tuple[UUID, ...]) -> dict[UUID, int]:
    settings = get_settings()
    database = DatabaseManager(settings.database)
    storage: S3ObjectStorage | None = None
    try:
        minio = settings.minio
        storage = await S3ObjectStorage.create(
            StorageConfig(
                provider=StorageProvider(minio.provider),
                region=minio.region,
                endpoint_url=str(minio.endpoint) if minio.endpoint is not None else None,
                access_key=minio.access_key.get_secret_value() if minio.access_key else None,
                secret_key=minio.secret_key.get_secret_value() if minio.secret_key else None,
                session_token=(
                    minio.session_token.get_secret_value() if minio.session_token else None
                ),
                connect_timeout_seconds=minio.connect_timeout_seconds,
                read_timeout_seconds=minio.read_timeout_seconds,
                multipart_part_size=minio.multipart_part_size,
            )
        )
        selected = campaign_ids
        if not selected:
            async with database.session() as session:
                selected = tuple(
                    await session.scalars(
                        select(distinct(CrawlPage.campaign_id)).where(
                            (CrawlPage.response_artifact_key.is_not(None))
                            | (CrawlPage.fingerprint_algorithm.is_not(None))
                        )
                    )
                )
        repository = CrawlRepository(database, storage)
        results: dict[UUID, int] = {}
        for campaign_id in sorted(set(selected), key=str):
            updated, grouped = await repository.backfill_fingerprints(campaign_id)
            results[campaign_id] = grouped
            print(f"{campaign_id}: fingerprinted {updated} retained artifacts")
        return results
    finally:
        if storage is not None:
            await storage.close()
        await database.close()


def main() -> None:
    arguments = _arguments()
    results = asyncio.run(backfill(tuple(arguments.campaign_id)))
    for campaign_id, count in results.items():
        print(f"{campaign_id}: grouped {count} fingerprinted pages")


if __name__ == "__main__":
    main()
