"""Provider-neutral object-storage contracts and validated metadata."""

from __future__ import annotations

import re
from collections.abc import AsyncIterable, AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol


class StorageProvider(StrEnum):
    """Supported S3-compatible provider modes."""

    MINIO = "minio"
    AWS = "aws"


class Bucket(StrEnum):
    """Private platform buckets with fixed responsibilities."""

    SCAN_ARTIFACTS = "scan-artifacts"
    DATASETS = "datasets"
    GENERATED_SITES = "generated-sites"
    MODEL_ARTIFACTS = "model-artifacts"
    USER_ASSETS = "user-assets"


ALL_BUCKETS = tuple(Bucket)
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_TAG_NAME = re.compile(r"^[A-Za-z0-9+\-=._:/@ ]{1,128}$")
_METADATA_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_RESERVED_METADATA = frozenset({"sha256", "retention-policy", "retain-until"})


def validate_object_key(value: str) -> str:
    """Reject traversal, ambiguous separators, controls, and oversized keys."""
    if not value or len(value.encode("utf-8")) > 1_024:
        raise ValueError("object key must contain between 1 and 1024 UTF-8 bytes")
    if value.startswith("/") or value.endswith("/") or "\\" in value or "%" in value:
        raise ValueError("object key must be relative and use forward slashes")
    segments = value.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError("object key contains an empty or traversal segment")
    if any(
        any(ord(character) < 32 or ord(character) == 127 for character in segment)
        for segment in segments
    ):
        raise ValueError("object key contains control characters")
    return value


@dataclass(frozen=True, slots=True)
class ObjectLocation:
    """A typed private bucket and validated object key."""

    bucket: Bucket
    key: str

    def __post_init__(self) -> None:
        validate_object_key(self.key)


@dataclass(frozen=True, slots=True)
class RetentionMetadata:
    """Application retention intent persisted with an object and relational metadata."""

    policy: str
    retain_until: datetime | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", self.policy):
            raise ValueError("retention policy must be a stable lowercase identifier")
        if self.retain_until is not None and self.retain_until.utcoffset() is None:
            raise ValueError("retention timestamp must be timezone-aware")

    def metadata(self) -> dict[str, str]:
        result = {"retention-policy": self.policy}
        if self.retain_until is not None:
            result["retain-until"] = self.retain_until.astimezone(UTC).isoformat()
        return result


@dataclass(frozen=True, slots=True)
class UploadRequest:
    """Immutable upload policy; a caller-computed checksum is mandatory."""

    expected_sha256: str
    content_type: str
    content_encoding: str | None = None
    tags: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)
    retention: RetentionMetadata | None = None
    test_artifact: bool = False

    def __post_init__(self) -> None:
        if not _SHA256.fullmatch(self.expected_sha256):
            raise ValueError("expected_sha256 must be a lowercase SHA-256 hex digest")
        if (
            not self.content_type
            or len(self.content_type) > 255
            or any(ord(character) < 32 for character in self.content_type)
        ):
            raise ValueError("content_type is invalid")
        if self.content_encoding not in {None, "gzip"}:
            raise ValueError("only gzip content encoding is supported")
        if len(self.tags) + int(self.test_artifact) > 10:
            raise ValueError("S3 objects support at most 10 tags")
        for key, value in self.tags.items():
            if not _TAG_NAME.fullmatch(key) or key.lower().startswith("aws:"):
                raise ValueError("object tag key is invalid or reserved")
            if len(value) > 256 or any(ord(character) < 32 for character in value):
                raise ValueError("object tag value is invalid")
        metadata_bytes = 0
        for key, value in self.metadata.items():
            if not _METADATA_NAME.fullmatch(key) or key in _RESERVED_METADATA:
                raise ValueError("object metadata key is invalid or reserved")
            if (
                not value
                or len(value.encode("utf-8")) > 2_048
                or not value.isascii()
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
            ):
                raise ValueError("object metadata value must be bounded printable ASCII")
            metadata_bytes += len(key) + len(value)
        if metadata_bytes > 7_000:
            raise ValueError("object metadata exceeds its bounded header budget")


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Verified immutable object metadata."""

    location: ObjectLocation
    sha256: str
    size: int
    content_type: str
    content_encoding: str | None
    tags: Mapping[str, str]
    retention: RetentionMetadata | None
    metadata: Mapping[str, str] = field(default_factory=dict)
    etag: str | None = None
    created: bool = True


@dataclass(frozen=True, slots=True)
class BucketReadiness:
    """Sanitized bucket readiness result."""

    bucket: Bucket
    ready: bool


@dataclass(frozen=True, slots=True)
class ApprovedUserAssetUpload:
    """Presign request that can only target the user-assets bucket."""

    location: ObjectLocation
    expected_sha256: str
    content_type: str
    expires_seconds: int = 300

    def __post_init__(self) -> None:
        if self.location.bucket is not Bucket.USER_ASSETS:
            raise ValueError("presigned uploads are restricted to user-assets")
        if not _SHA256.fullmatch(self.expected_sha256):
            raise ValueError("expected_sha256 must be a lowercase SHA-256 hex digest")
        if (
            not self.content_type
            or len(self.content_type) > 255
            or any(ord(character) < 32 for character in self.content_type)
        ):
            raise ValueError("content_type is invalid")
        if not 60 <= self.expires_seconds <= 900:
            raise ValueError("upload URL expiry must be between 60 and 900 seconds")


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    """Approved URL plus the exact headers the browser must send."""

    url: str
    required_headers: Mapping[str, str]
    expires_seconds: int


@dataclass(frozen=True, slots=True)
class StorageConfig:
    """MinIO development or AWS credential-chain S3 configuration."""

    provider: StorageProvider
    region: str = "us-east-1"
    endpoint_url: str | None = None
    access_key: str | None = field(default=None, repr=False)
    secret_key: str | None = field(default=None, repr=False)
    session_token: str | None = field(default=None, repr=False)
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 60.0
    multipart_part_size: int = 8 * 1_024 * 1_024

    def __post_init__(self) -> None:
        if self.provider is StorageProvider.MINIO:
            if self.endpoint_url is None or not self.endpoint_url.startswith(
                ("http://", "https://")
            ):
                raise ValueError("MinIO requires an explicit HTTP(S) endpoint")
            if not self.access_key or not self.secret_key:
                raise ValueError("MinIO requires explicit development credentials")
        elif self.endpoint_url is not None:
            raise ValueError("AWS mode uses the SDK endpoint and does not accept endpoint_url")
        if (self.access_key is None) != (self.secret_key is None):
            raise ValueError("access_key and secret_key must be supplied together")
        if not 5 * 1_024 * 1_024 <= self.multipart_part_size <= 128 * 1_024 * 1_024:
            raise ValueError("multipart part size must be between 5 MiB and 128 MiB")


class ObjectConflictError(RuntimeError):
    """The immutable key already contains different content."""


class ChecksumMismatchError(RuntimeError):
    """Uploaded or downloaded bytes do not match their declared SHA-256."""


class ObjectNotFoundError(RuntimeError):
    """The requested private object does not exist."""


class ObjectStorage(Protocol):
    """Async-safe private object-storage boundary."""

    async def readiness(self) -> tuple[BucketReadiness, ...]: ...

    async def upload(
        self,
        location: ObjectLocation,
        stream: AsyncIterable[bytes],
        request: UploadRequest,
    ) -> StoredObject: ...

    def stream_download(
        self,
        location: ObjectLocation,
        *,
        expected_sha256: str | None = None,
        chunk_size: int = 64 * 1_024,
    ) -> AsyncIterator[bytes]: ...

    async def stat(self, location: ObjectLocation) -> StoredObject | None: ...

    async def presign_read(
        self, location: ObjectLocation, *, expires_seconds: int = 300
    ) -> str: ...

    async def presign_user_asset_upload(
        self, request: ApprovedUserAssetUpload
    ) -> PresignedUpload: ...

    async def list_test_artifacts(self) -> tuple[StoredObject, ...]: ...

    async def remove_test_artifact(self, location: ObjectLocation) -> None: ...

    async def close(self) -> None: ...
