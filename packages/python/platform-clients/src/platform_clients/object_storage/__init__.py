"""S3-compatible object-storage abstractions."""

from platform_clients.object_storage.fake import InMemoryObjectStorage
from platform_clients.object_storage.keys import (
    dataset_key,
    generated_site_key,
    model_key,
    scan_key,
    user_asset_key,
)
from platform_clients.object_storage.models import (
    Bucket,
    ObjectLocation,
    ObjectStorage,
    StorageConfig,
    UploadRequest,
)
from platform_clients.object_storage.s3 import S3ObjectStorage
from platform_clients.object_storage.scan_artifacts import (
    ArtifactAccessPolicy,
    ArtifactProvenanceStatus,
    ArtifactRetentionStatus,
    ScanArtifactKind,
    ScanObjectMetadata,
)

__all__ = [
    "ArtifactAccessPolicy",
    "ArtifactProvenanceStatus",
    "ArtifactRetentionStatus",
    "Bucket",
    "InMemoryObjectStorage",
    "ObjectLocation",
    "ObjectStorage",
    "S3ObjectStorage",
    "ScanArtifactKind",
    "ScanObjectMetadata",
    "StorageConfig",
    "UploadRequest",
    "dataset_key",
    "generated_site_key",
    "model_key",
    "scan_key",
    "user_asset_key",
]
