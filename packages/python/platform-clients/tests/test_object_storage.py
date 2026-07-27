"""Unit tests for provider-neutral object-storage behavior."""

import gzip
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from platform_clients.object_storage.fake import InMemoryObjectStorage
from platform_clients.object_storage.gzip import gzip_html, gzip_json
from platform_clients.object_storage.keys import (
    dataset_key,
    generated_site_key,
    model_key,
    safe_filename,
    scan_key,
    user_asset_key,
)
from platform_clients.object_storage.metadata import (
    ArtifactMetadataRecord,
    InMemoryArtifactMetadataRepository,
)
from platform_clients.object_storage.models import (
    ALL_BUCKETS,
    ApprovedUserAssetUpload,
    Bucket,
    ChecksumMismatchError,
    ObjectConflictError,
    ObjectLocation,
    RetentionMetadata,
    StorageConfig,
    StorageProvider,
    UploadRequest,
)


async def chunks(*values: bytes) -> AsyncIterator[bytes]:
    for value in values:
        yield value


async def collect(stream: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in stream])


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def test_typed_key_builders_match_storage_layout() -> None:
    first, second = uuid4(), uuid4()

    assert scan_key(first, second, "html/index.html").key == (
        f"scans/{first}/{second}/html/index.html"
    )
    assert dataset_key(first, second, "manifest.json").key == (
        f"datasets/{first}/{second}/manifest.json"
    )
    assert generated_site_key(first, second, "pages/index.html").key == (
        f"generated/{first}/{second}/pages/index.html"
    )
    assert model_key(first, second, "adapter.bin").key == (f"models/{first}/{second}/adapter.bin")
    assert user_asset_key(first, second, "My logo!!.PNG").key == (
        f"user-assets/{first}/{second}/My-logo.png"
    )


@pytest.mark.parametrize(
    "unsafe",
    [
        "../secret",
        "pages/../../secret",
        "/absolute",
        "pages\\secret",
        "pages/%2e%2e/key",
        "pages//secret",
        "pages/",
    ],
)
def test_key_builders_reject_traversal_and_ambiguous_paths(unsafe: str) -> None:
    with pytest.raises(ValueError):
        dataset_key(uuid4(), uuid4(), unsafe)


def test_safe_filename_never_retains_a_path() -> None:
    assert safe_filename("résumé final.JSON") == "resume-final.json"
    with pytest.raises(ValueError):
        safe_filename("../../credentials")


def test_untyped_locations_reject_percent_encoded_traversal() -> None:
    with pytest.raises(ValueError):
        ObjectLocation(Bucket.DATASETS, "datasets/id/version/%2e%2e/secret")


def test_storage_configuration_separates_minio_and_aws() -> None:
    minio = StorageConfig(
        provider=StorageProvider.MINIO,
        endpoint_url="http://127.0.0.1:9000",
        access_key="local-access",
        secret_key="local-secret",  # pragma: allowlist secret  # noqa: S106
    )
    aws = StorageConfig(provider=StorageProvider.AWS)

    assert minio.endpoint_url is not None
    assert aws.endpoint_url is None
    with pytest.raises(ValueError, match="does not accept endpoint"):
        StorageConfig(provider=StorageProvider.AWS, endpoint_url="https://s3.example.test")


@pytest.mark.anyio
async def test_fake_upload_is_verified_idempotent_and_immutable() -> None:
    storage = InMemoryObjectStorage()
    body = b"verified artifact"
    location = dataset_key(uuid4(), uuid4(), "manifest.json")
    retention = RetentionMetadata(
        policy="dataset-version", retain_until=datetime.now(UTC) + timedelta(days=30)
    )
    request = UploadRequest(
        expected_sha256=sha256(body),
        content_type="application/json",
        tags={"kind": "manifest"},
        retention=retention,
        test_artifact=True,
    )

    created = await storage.upload(location, chunks(body[:4], body[4:]), request)
    repeated = await storage.upload(location, chunks(body), request)

    assert created.created
    assert not repeated.created
    assert created.tags["aiwg-test-artifact"] == "true"
    assert created.retention == retention
    assert await collect(storage.stream_download(location)) == body
    assert len(await storage.list_test_artifacts()) == 1

    conflicting = b"different"
    with pytest.raises(ObjectConflictError):
        await storage.upload(
            location,
            chunks(conflicting),
            UploadRequest(expected_sha256=sha256(conflicting), content_type="application/json"),
        )
    with pytest.raises(ObjectConflictError):
        await storage.upload(
            location,
            chunks(body),
            UploadRequest(expected_sha256=sha256(body), content_type="text/plain"),
        )


@pytest.mark.anyio
async def test_fake_rejects_upload_and_download_checksum_mismatches() -> None:
    storage = InMemoryObjectStorage()
    location = scan_key(uuid4(), uuid4(), "page.html")
    with pytest.raises(ChecksumMismatchError):
        await storage.upload(
            location,
            chunks(b"actual"),
            UploadRequest(expected_sha256=sha256(b"expected"), content_type="text/html"),
        )

    body = b"actual"
    await storage.upload(
        location,
        chunks(body),
        UploadRequest(expected_sha256=sha256(body), content_type="text/html"),
    )
    with pytest.raises(ChecksumMismatchError):
        await collect(storage.stream_download(location, expected_sha256=sha256(b"wrong")))


@pytest.mark.anyio
async def test_presigned_uploads_are_limited_to_typed_user_assets() -> None:
    storage = InMemoryObjectStorage()
    body = b"image"
    location = user_asset_key(uuid4(), uuid4(), "image.png")
    signed = await storage.presign_user_asset_upload(
        ApprovedUserAssetUpload(
            location=location,
            expected_sha256=sha256(body),
            content_type="image/png",
        )
    )

    assert "approved-upload" in signed.url
    assert signed.required_headers["content-type"] == "image/png"
    with pytest.raises(ValueError, match="restricted"):
        ApprovedUserAssetUpload(
            location=ObjectLocation(Bucket.DATASETS, "datasets/example/object.json"),
            expected_sha256=sha256(body),
            content_type="application/json",
        )


@pytest.mark.anyio
async def test_gzip_helpers_round_trip_deterministic_html_and_json() -> None:
    html = "<!doctype html><title>Safe</title>"
    html_compressed = await collect(gzip_html(html))
    json_compressed = await collect(gzip_json({"z": 1, "a": [True, None]}))

    assert gzip.decompress(html_compressed).decode() == html
    assert json.loads(gzip.decompress(json_compressed)) == {"a": [True, None], "z": 1}


@pytest.mark.anyio
async def test_metadata_repository_is_idempotent() -> None:
    repository = InMemoryArtifactMetadataRepository()
    artifact_id = uuid4()
    record = ArtifactMetadataRecord(
        artifact_id=artifact_id,
        owner_id=uuid4(),
        location=model_key(uuid4(), uuid4(), "model.bin"),
        sha256=sha256(b"model"),
        size=5,
        content_type="application/octet-stream",
        retention=None,
        created_at=datetime.now(UTC),
    )

    await repository.record(record)
    await repository.record(record)

    assert await repository.get(artifact_id) == record
    await repository.remove(artifact_id)
    assert await repository.get(artifact_id) is None


@pytest.mark.anyio
async def test_bucket_readiness_and_safe_test_cleanup() -> None:
    storage = InMemoryObjectStorage()
    assert tuple(result.bucket for result in await storage.readiness()) == ALL_BUCKETS
    location = generated_site_key(uuid4(), uuid4(), "index.html")
    body = b"site"
    await storage.upload(
        location,
        chunks(body),
        UploadRequest(expected_sha256=sha256(body), content_type="text/html"),
    )

    with pytest.raises(PermissionError):
        await storage.remove_test_artifact(location)
