"""Deterministic in-memory object storage for unit tests and fake dependency mode."""

import base64
import hashlib
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import replace
from urllib.parse import quote

from platform_clients.object_storage.models import (
    ALL_BUCKETS,
    ApprovedUserAssetUpload,
    BucketReadiness,
    ChecksumMismatchError,
    ObjectConflictError,
    ObjectLocation,
    ObjectNotFoundError,
    PresignedUpload,
    StoredObject,
    UploadRequest,
)


class InMemoryObjectStorage:
    """Private-bucket behavior without network or filesystem I/O."""

    def __init__(self) -> None:
        self._objects: dict[ObjectLocation, tuple[bytes, StoredObject]] = {}

    async def readiness(self) -> tuple[BucketReadiness, ...]:
        return tuple(BucketReadiness(bucket=bucket, ready=True) for bucket in ALL_BUCKETS)

    async def upload(
        self,
        location: ObjectLocation,
        stream: AsyncIterable[bytes],
        request: UploadRequest,
    ) -> StoredObject:
        chunks: list[bytes] = []
        async for chunk in stream:
            if not isinstance(chunk, bytes):
                raise TypeError("upload stream must yield bytes")
            chunks.append(chunk)
        body = b"".join(chunks)
        digest = hashlib.sha256(body).hexdigest()
        if digest != request.expected_sha256:
            raise ChecksumMismatchError("upload SHA-256 does not match expected digest")
        existing = self._objects.get(location)
        if existing is not None:
            expected_tags = dict(request.tags)
            if request.test_artifact:
                expected_tags["aiwg-test-artifact"] = "true"
            if (
                existing[1].sha256 == digest
                and existing[1].content_type == request.content_type
                and existing[1].content_encoding == request.content_encoding
                and dict(existing[1].tags) == expected_tags
                and existing[1].retention == request.retention
            ):
                return replace(existing[1], created=False)
            raise ObjectConflictError("immutable object key contains different content or metadata")
        tags = dict(request.tags)
        if request.test_artifact:
            tags["aiwg-test-artifact"] = "true"
        stored = StoredObject(
            location=location,
            sha256=digest,
            size=len(body),
            content_type=request.content_type,
            content_encoding=request.content_encoding,
            tags=tags,
            retention=request.retention,
            etag=digest,
        )
        self._objects[location] = (body, stored)
        return stored

    async def stat(self, location: ObjectLocation) -> StoredObject | None:
        existing = self._objects.get(location)
        return None if existing is None else existing[1]

    async def _body(self, location: ObjectLocation) -> tuple[bytes, StoredObject]:
        existing = self._objects.get(location)
        if existing is None:
            raise ObjectNotFoundError(f"object not found: {location.bucket.value}/{location.key}")
        return existing

    async def _verified_chunks(
        self,
        location: ObjectLocation,
        *,
        expected_sha256: str | None,
        chunk_size: int,
    ) -> AsyncIterator[bytes]:
        if not 1 <= chunk_size <= 8 * 1_024 * 1_024:
            raise ValueError("download chunk size must be between 1 byte and 8 MiB")
        body, stored = await self._body(location)
        digest = hashlib.sha256()
        for offset in range(0, len(body), chunk_size):
            chunk = body[offset : offset + chunk_size]
            digest.update(chunk)
            yield chunk
        expected = expected_sha256 or stored.sha256
        if digest.hexdigest() != expected:
            raise ChecksumMismatchError("download SHA-256 does not match expected digest")

    def stream_download(
        self,
        location: ObjectLocation,
        *,
        expected_sha256: str | None = None,
        chunk_size: int = 64 * 1_024,
    ) -> AsyncIterator[bytes]:
        return self._verified_chunks(
            location, expected_sha256=expected_sha256, chunk_size=chunk_size
        )

    async def presign_read(self, location: ObjectLocation, *, expires_seconds: int = 300) -> str:
        if not 60 <= expires_seconds <= 3_600:
            raise ValueError("read URL expiry must be between 60 and 3600 seconds")
        if location not in self._objects:
            raise ObjectNotFoundError("cannot sign a missing object")
        return (
            f"https://storage.invalid/{location.bucket.value}/{quote(location.key)}"
            f"?operation=read&expires={expires_seconds}"
        )

    async def presign_user_asset_upload(self, request: ApprovedUserAssetUpload) -> PresignedUpload:
        return PresignedUpload(
            url=(
                f"https://storage.invalid/{request.location.bucket.value}/"
                f"{quote(request.location.key)}?operation=approved-upload"
                f"&expires={request.expires_seconds}"
            ),
            required_headers={
                "content-type": request.content_type,
                "x-amz-checksum-sha256": base64.b64encode(
                    bytes.fromhex(request.expected_sha256)
                ).decode("ascii"),
            },
            expires_seconds=request.expires_seconds,
        )

    async def list_test_artifacts(self) -> tuple[StoredObject, ...]:
        return tuple(
            stored
            for _, stored in self._objects.values()
            if stored.tags.get("aiwg-test-artifact") == "true"
        )

    async def remove_test_artifact(self, location: ObjectLocation) -> None:
        existing = self._objects.get(location)
        if existing is None:
            return
        if existing[1].tags.get("aiwg-test-artifact") != "true":
            raise PermissionError("only tagged development test artifacts may be removed")
        del self._objects[location]

    async def close(self) -> None:
        return None
