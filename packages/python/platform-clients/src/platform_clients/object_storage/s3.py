"""Async MinIO/AWS S3 implementation with immutable verified uploads."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import AbstractAsyncContextManager, suppress
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, cast
from urllib.parse import urlencode

from aiobotocore.config import AioConfig
from aiobotocore.session import get_session
from botocore.exceptions import ClientError
from types_aiobotocore_s3.client import S3Client
from types_aiobotocore_s3.type_defs import CompletedPartTypeDef

from platform_clients.object_storage.models import (
    ALL_BUCKETS,
    ApprovedUserAssetUpload,
    BucketReadiness,
    ChecksumMismatchError,
    ObjectConflictError,
    ObjectLocation,
    ObjectNotFoundError,
    PresignedUpload,
    RetentionMetadata,
    StorageConfig,
    StorageProvider,
    StoredObject,
    UploadRequest,
)


def _checksum_base64(hex_digest: str) -> str:
    return base64.b64encode(bytes.fromhex(hex_digest)).decode("ascii")


def _is_missing(error: ClientError) -> bool:
    code = str(error.response.get("Error", {}).get("Code", ""))
    return code in {"404", "NoSuchKey", "NotFound"}


def _is_precondition(error: ClientError) -> bool:
    code = str(error.response.get("Error", {}).get("Code", ""))
    return code in {"409", "412", "ConditionalRequestConflict", "PreconditionFailed"}


@dataclass(frozen=True, slots=True)
class _UploadedPart:
    etag: str
    number: int
    checksum: str | None
    size: int

    def completion(self) -> CompletedPartTypeDef:
        result = CompletedPartTypeDef(ETag=self.etag, PartNumber=self.number)
        if self.checksum is not None:
            result["ChecksumSHA256"] = self.checksum
        return result


class S3ObjectStorage:
    """Private-bucket object storage backed by one process-owned async S3 client."""

    def __init__(
        self,
        config: StorageConfig,
        client: S3Client,
        client_context: AbstractAsyncContextManager[S3Client],
    ) -> None:
        self._config = config
        self._client = client
        self._client_context = client_context
        self._closed = False

    @classmethod
    async def create(cls, config: StorageConfig) -> S3ObjectStorage:
        """Create a MinIO path-style or AWS SDK-default asynchronous client."""
        session = get_session()
        client_config = AioConfig(
            connect_timeout=config.connect_timeout_seconds,
            read_timeout=config.read_timeout_seconds,
            retries={"mode": "standard", "max_attempts": 4},
            signature_version="s3v4",
            s3={"addressing_style": "path" if config.provider is StorageProvider.MINIO else "auto"},
        )
        context = cast(
            AbstractAsyncContextManager[S3Client],
            session.create_client(
                "s3",
                region_name=config.region,
                endpoint_url=config.endpoint_url,
                aws_access_key_id=config.access_key,
                aws_secret_access_key=config.secret_key,
                aws_session_token=config.session_token,
                config=client_config,
            ),
        )
        client = await context.__aenter__()
        return cls(config, client, context)

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._client_context.__aexit__(None, None, None)

    async def readiness(self) -> tuple[BucketReadiness, ...]:
        results: list[BucketReadiness] = []
        for bucket in ALL_BUCKETS:
            try:
                await self._client.head_bucket(Bucket=bucket.value)
            except ClientError:
                results.append(BucketReadiness(bucket=bucket, ready=False))
            else:
                results.append(BucketReadiness(bucket=bucket, ready=True))
        return tuple(results)

    async def _tags(self, location: ObjectLocation) -> dict[str, str]:
        response = await self._client.get_object_tagging(
            Bucket=location.bucket.value, Key=location.key
        )
        return {item["Key"]: item["Value"] for item in response.get("TagSet", [])}

    async def stat(self, location: ObjectLocation) -> StoredObject | None:
        try:
            response = await self._client.head_object(
                Bucket=location.bucket.value,
                Key=location.key,
                ChecksumMode="ENABLED",
            )
        except ClientError as error:
            if _is_missing(error):
                return None
            raise
        metadata = dict(response.get("Metadata", {}))
        digest = metadata.get("sha256")
        if digest is None:
            server_checksum = response.get("ChecksumSHA256")
            if server_checksum is None or "-" in server_checksum:
                raise ChecksumMismatchError("stored object has no SHA-256 metadata")
            try:
                digest = base64.b64decode(server_checksum, validate=True).hex()
            except ValueError as error:
                raise ChecksumMismatchError("stored object has invalid SHA-256 metadata") from error
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ChecksumMismatchError("stored object has invalid SHA-256 metadata")
        retention = None
        policy = metadata.get("retention-policy")
        if policy is not None:
            retain_until = metadata.get("retain-until")
            retention = RetentionMetadata(
                policy=policy,
                retain_until=datetime.fromisoformat(retain_until) if retain_until else None,
            )
        custom_metadata = {
            key: value
            for key, value in metadata.items()
            if key not in {"sha256", "retention-policy", "retain-until"}
        }
        return StoredObject(
            location=location,
            sha256=digest,
            size=response["ContentLength"],
            content_type=response.get("ContentType", "application/octet-stream"),
            content_encoding=response.get("ContentEncoding"),
            tags=await self._tags(location),
            retention=retention,
            metadata=custom_metadata,
            etag=response.get("ETag", "").strip('"') or None,
        )

    @staticmethod
    def _metadata(request: UploadRequest) -> dict[str, str]:
        metadata = {"sha256": request.expected_sha256, **request.metadata}
        if request.retention is not None:
            metadata.update(request.retention.metadata())
        return metadata

    @staticmethod
    def _tagging(request: UploadRequest) -> tuple[dict[str, str], str]:
        tags = dict(request.tags)
        if request.test_artifact:
            tags["aiwg-test-artifact"] = "true"
        return tags, urlencode(sorted(tags.items()))

    @classmethod
    def _matches_request(cls, stored: StoredObject, request: UploadRequest) -> bool:
        tags, _ = cls._tagging(request)
        return (
            stored.sha256 == request.expected_sha256
            and stored.content_type == request.content_type
            and stored.content_encoding == request.content_encoding
            and dict(stored.tags) == tags
            and dict(stored.metadata) == dict(request.metadata)
            and stored.retention == request.retention
        )

    async def upload(
        self,
        location: ObjectLocation,
        stream: AsyncIterable[bytes],
        request: UploadRequest,
    ) -> StoredObject:
        existing = await self.stat(location)
        if existing is not None:
            if self._matches_request(existing, request):
                return replace(existing, created=False)
            raise ObjectConflictError("immutable object key contains different content or metadata")

        buffer = bytearray()
        digest = hashlib.sha256()
        upload_id: str | None = None
        parts: list[_UploadedPart] = []
        tags, tagging = self._tagging(request)
        try:
            async for chunk in stream:
                if not isinstance(chunk, bytes):
                    raise TypeError("upload stream must yield bytes")
                digest.update(chunk)
                buffer.extend(chunk)
                if upload_id is None and len(buffer) >= self._config.multipart_part_size:
                    upload_id = await self._start_multipart(location, request, tagging)
                while upload_id is not None and len(buffer) >= self._config.multipart_part_size:
                    part = bytes(buffer[: self._config.multipart_part_size])
                    del buffer[: self._config.multipart_part_size]
                    parts.append(await self._upload_part(location, upload_id, len(parts) + 1, part))
                    if len(parts) >= 10_000:
                        raise ValueError("multipart upload exceeds the S3 10000-part limit")

            actual_sha256 = digest.hexdigest()
            if actual_sha256 != request.expected_sha256:
                raise ChecksumMismatchError("upload SHA-256 does not match expected digest")
            if upload_id is None:
                return await self._put_small(location, bytes(buffer), request, tags, tagging)
            if buffer:
                parts.append(
                    await self._upload_part(location, upload_id, len(parts) + 1, bytes(buffer))
                )
            try:
                response = await self._client.complete_multipart_upload(
                    Bucket=location.bucket.value,
                    Key=location.key,
                    UploadId=upload_id,
                    MultipartUpload={"Parts": [part.completion() for part in parts]},
                    IfNoneMatch="*",
                )
            except ClientError as error:
                if not _is_precondition(error):
                    raise
                existing = await self.stat(location)
                if existing is not None and self._matches_request(existing, request):
                    return replace(existing, created=False)
                raise ObjectConflictError(
                    "immutable object key won a conflicting multipart upload race"
                ) from error
            return StoredObject(
                location=location,
                sha256=actual_sha256,
                size=sum(part.size for part in parts),
                content_type=request.content_type,
                content_encoding=request.content_encoding,
                tags=tags,
                retention=request.retention,
                metadata=dict(request.metadata),
                etag=response.get("ETag", "").strip('"') or None,
            )
        except BaseException:
            if upload_id is not None:
                with suppress(ClientError):
                    await asyncio.shield(
                        self._client.abort_multipart_upload(
                            Bucket=location.bucket.value,
                            Key=location.key,
                            UploadId=upload_id,
                        )
                    )
            raise

    async def _start_multipart(
        self, location: ObjectLocation, request: UploadRequest, tagging: str
    ) -> str:
        parameters: dict[str, Any] = {
            "Bucket": location.bucket.value,
            "Key": location.key,
            "ContentType": request.content_type,
            "Metadata": self._metadata(request),
            "ChecksumAlgorithm": "SHA256",
        }
        if tagging:
            parameters["Tagging"] = tagging
        if request.content_encoding is not None:
            parameters["ContentEncoding"] = request.content_encoding
        response = await self._client.create_multipart_upload(**parameters)
        return response["UploadId"]

    async def _upload_part(
        self, location: ObjectLocation, upload_id: str, part_number: int, body: bytes
    ) -> _UploadedPart:
        part_checksum = hashlib.sha256(body).digest()
        response = await self._client.upload_part(
            Bucket=location.bucket.value,
            Key=location.key,
            UploadId=upload_id,
            PartNumber=part_number,
            Body=body,
            ChecksumSHA256=base64.b64encode(part_checksum).decode("ascii"),
        )
        return _UploadedPart(
            etag=response["ETag"],
            number=part_number,
            checksum=response.get("ChecksumSHA256"),
            size=len(body),
        )

    async def _put_small(
        self,
        location: ObjectLocation,
        body: bytes,
        request: UploadRequest,
        tags: dict[str, str],
        tagging: str,
    ) -> StoredObject:
        parameters: dict[str, Any] = {
            "Bucket": location.bucket.value,
            "Key": location.key,
            "Body": body,
            "ContentType": request.content_type,
            "Metadata": self._metadata(request),
            "ChecksumSHA256": _checksum_base64(request.expected_sha256),
            "IfNoneMatch": "*",
        }
        if tagging:
            parameters["Tagging"] = tagging
        if request.content_encoding is not None:
            parameters["ContentEncoding"] = request.content_encoding
        try:
            response = await self._client.put_object(**parameters)
        except ClientError as error:
            if not _is_precondition(error):
                raise
            existing = await self.stat(location)
            if existing is not None and self._matches_request(existing, request):
                return replace(existing, created=False)
            raise ObjectConflictError(
                "immutable object key won a conflicting upload race"
            ) from error
        return StoredObject(
            location=location,
            sha256=request.expected_sha256,
            size=len(body),
            content_type=request.content_type,
            content_encoding=request.content_encoding,
            tags=tags,
            retention=request.retention,
            metadata=dict(request.metadata),
            etag=response.get("ETag", "").strip('"') or None,
        )

    async def _download(
        self,
        location: ObjectLocation,
        *,
        expected_sha256: str | None,
        chunk_size: int,
    ) -> AsyncIterator[bytes]:
        if not 1 <= chunk_size <= 8 * 1_024 * 1_024:
            raise ValueError("download chunk size must be between 1 byte and 8 MiB")
        stored = await self.stat(location)
        if stored is None:
            raise ObjectNotFoundError("object does not exist")
        expected = expected_sha256 or stored.sha256
        try:
            response = await self._client.get_object(
                Bucket=location.bucket.value, Key=location.key, ChecksumMode="ENABLED"
            )
        except ClientError as error:
            if _is_missing(error):
                raise ObjectNotFoundError("object does not exist") from error
            raise
        digest = hashlib.sha256()
        body = response["Body"]
        async with body:
            while chunk := await body.read(chunk_size):
                digest.update(chunk)
                yield chunk
        if digest.hexdigest() != expected:
            raise ChecksumMismatchError("download SHA-256 does not match expected digest")

    def stream_download(
        self,
        location: ObjectLocation,
        *,
        expected_sha256: str | None = None,
        chunk_size: int = 64 * 1_024,
    ) -> AsyncIterator[bytes]:
        return self._download(location, expected_sha256=expected_sha256, chunk_size=chunk_size)

    async def presign_read(self, location: ObjectLocation, *, expires_seconds: int = 300) -> str:
        if not 60 <= expires_seconds <= 3_600:
            raise ValueError("read URL expiry must be between 60 and 3600 seconds")
        if await self.stat(location) is None:
            raise ObjectNotFoundError("cannot sign a missing object")
        return await self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": location.bucket.value, "Key": location.key},
            ExpiresIn=expires_seconds,
            HttpMethod="GET",
        )

    async def presign_user_asset_upload(self, request: ApprovedUserAssetUpload) -> PresignedUpload:
        checksum = _checksum_base64(request.expected_sha256)
        parameters = {
            "Bucket": request.location.bucket.value,
            "Key": request.location.key,
            "ContentType": request.content_type,
            "ChecksumSHA256": checksum,
            "Metadata": {"sha256": request.expected_sha256},
            "IfNoneMatch": "*",
        }
        url = await self._client.generate_presigned_url(
            "put_object",
            Params=parameters,
            ExpiresIn=request.expires_seconds,
            HttpMethod="PUT",
        )
        return PresignedUpload(
            url=url,
            required_headers={
                "content-type": request.content_type,
                "if-none-match": "*",
                "x-amz-checksum-sha256": checksum,
                "x-amz-meta-sha256": request.expected_sha256,
            },
            expires_seconds=request.expires_seconds,
        )

    async def list_test_artifacts(self) -> tuple[StoredObject, ...]:
        results: list[StoredObject] = []
        for bucket in ALL_BUCKETS:
            continuation: str | None = None
            while True:
                parameters: dict[str, Any] = {"Bucket": bucket.value}
                if continuation is not None:
                    parameters["ContinuationToken"] = continuation
                response = await self._client.list_objects_v2(**parameters)
                for item in response.get("Contents", []):
                    location = ObjectLocation(bucket, item["Key"])
                    tags = await self._tags(location)
                    if tags.get("aiwg-test-artifact") == "true":
                        stored = await self.stat(location)
                        if stored is not None:
                            results.append(stored)
                if not response.get("IsTruncated"):
                    break
                continuation = response.get("NextContinuationToken")
        return tuple(results)

    async def remove_test_artifact(self, location: ObjectLocation) -> None:
        stored = await self.stat(location)
        if stored is None:
            return
        if stored.tags.get("aiwg-test-artifact") != "true":
            raise PermissionError("only tagged development test artifacts may be removed")
        await self._client.delete_object(Bucket=location.bucket.value, Key=location.key)
