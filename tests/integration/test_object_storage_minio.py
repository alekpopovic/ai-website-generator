"""Opt-in MinIO integration coverage for S3-compatible storage."""

import hashlib
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from platform_clients.object_storage.keys import scan_key, user_asset_key
from platform_clients.object_storage.models import (
    ApprovedUserAssetUpload,
    ObjectLocation,
    RetentionMetadata,
    StorageConfig,
    StorageProvider,
    UploadRequest,
)
from platform_clients.object_storage.s3 import S3ObjectStorage

pytestmark = pytest.mark.integration


def minio_config() -> StorageConfig:
    if os.environ.get("MINIO_INTEGRATION_TESTS") != "true":
        pytest.skip("set MINIO_INTEGRATION_TESTS=true to run MinIO integration tests")
    endpoint = os.environ.get("MINIO_ENDPOINT")
    access_key = os.environ.get("MINIO_ACCESS_KEY")
    secret_key = os.environ.get("MINIO_SECRET_KEY")
    if not endpoint or not access_key or not secret_key:
        pytest.fail("MINIO_ENDPOINT, MINIO_ACCESS_KEY, and MINIO_SECRET_KEY are required")
    return StorageConfig(
        provider=StorageProvider.MINIO,
        endpoint_url=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        multipart_part_size=5 * 1_024 * 1_024,
    )


async def body_stream(body: bytes, *, chunk_size: int = 256 * 1_024) -> AsyncIterator[bytes]:
    for offset in range(0, len(body), chunk_size):
        yield body[offset : offset + chunk_size]


async def download(storage: S3ObjectStorage, location: ObjectLocation) -> bytes:
    return b"".join([chunk async for chunk in storage.stream_download(location)])


@pytest.mark.anyio
async def test_minio_readiness_streams_multipart_metadata_and_presigning() -> None:
    storage = await S3ObjectStorage.create(minio_config())
    website_id, scan_id = uuid4(), uuid4()
    small_location = scan_key(website_id, scan_id, "integration-small.json")
    multipart_location = scan_key(website_id, scan_id, "integration-multipart.bin")
    created_locations = [small_location, multipart_location]
    try:
        assert all(result.ready for result in await storage.readiness())
        small = b'{"integration":true}'
        small_digest = hashlib.sha256(small).hexdigest()
        request = UploadRequest(
            expected_sha256=small_digest,
            content_type="application/json",
            tags={"suite": "minio"},
            retention=RetentionMetadata(
                policy="integration-test", retain_until=datetime.now(UTC) + timedelta(days=1)
            ),
            test_artifact=True,
        )
        created = await storage.upload(small_location, body_stream(small), request)
        repeated = await storage.upload(small_location, body_stream(small), request)

        assert created.created
        assert not repeated.created
        assert await download(storage, small_location) == small
        assert created.content_type == "application/json"
        stored = await storage.stat(small_location)
        assert stored is not None
        assert stored.tags["suite"] == "minio"
        assert "X-Amz-" in await storage.presign_read(small_location)

        multipart = b"m" * (5 * 1_024 * 1_024 + 257)
        multipart_digest = hashlib.sha256(multipart).hexdigest()
        uploaded = await storage.upload(
            multipart_location,
            body_stream(multipart),
            UploadRequest(
                expected_sha256=multipart_digest,
                content_type="application/octet-stream",
                test_artifact=True,
            ),
        )
        assert uploaded.size == len(multipart)
        assert await download(storage, multipart_location) == multipart

        approved = await storage.presign_user_asset_upload(
            ApprovedUserAssetUpload(
                location=user_asset_key(uuid4(), uuid4(), "approved.png"),
                expected_sha256=hashlib.sha256(b"image").hexdigest(),
                content_type="image/png",
            )
        )
        assert "X-Amz-" in approved.url
        assert approved.required_headers["if-none-match"] == "*"
    finally:
        for location in created_locations:
            await storage.remove_test_artifact(location)
        await storage.close()
