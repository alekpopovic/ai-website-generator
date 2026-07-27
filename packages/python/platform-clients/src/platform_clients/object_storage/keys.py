"""Typed object-key builders with traversal-safe path normalization."""

import re
import unicodedata
from pathlib import PurePosixPath
from uuid import UUID

from platform_clients.object_storage.models import Bucket, ObjectLocation, validate_object_key


def safe_filename(value: str, *, max_length: int = 120) -> str:
    """Normalize one untrusted display filename without retaining any path."""
    if not value or value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError("filename must be one path-free component")
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    stem, separator, suffix = ascii_value.rpartition(".")
    extension = (
        f".{suffix.lower()}" if separator and re.fullmatch(r"[A-Za-z0-9]{1,10}", suffix) else ""
    )
    source_stem = stem if extension else ascii_value
    normalized_stem = re.sub(r"[^A-Za-z0-9_-]+", "-", source_stem).strip("-_")
    normalized_stem = re.sub(r"[-_]{2,}", "-", normalized_stem) or "artifact"
    available = max(1, max_length - len(extension))
    return f"{normalized_stem[:available].rstrip('-_') or 'artifact'}{extension}"


def safe_relative_path(value: str) -> str:
    """Normalize each segment while rejecting traversal before transformation."""
    if not value or value.startswith("/") or "\\" in value or "%" in value:
        raise ValueError("artifact path must be a relative decoded path")
    raw_segments = value.split("/")
    if any(segment in {"", ".", ".."} for segment in raw_segments):
        raise ValueError("artifact path contains traversal or empty segments")
    path = PurePosixPath(value)
    normalized = "/".join(safe_filename(part) for part in path.parts)
    return validate_object_key(normalized)


def _location(
    bucket: Bucket, domain: str, prefix: tuple[str, ...], artifact_path: str
) -> ObjectLocation:
    identifiers = tuple(str(UUID(value)) for value in prefix)
    return ObjectLocation(
        bucket, "/".join((domain, *identifiers, safe_relative_path(artifact_path)))
    )


def scan_key(website_id: UUID, page_scan_id: UUID, artifact_path: str) -> ObjectLocation:
    return _location(
        Bucket.SCAN_ARTIFACTS,
        "scans",
        (str(website_id), str(page_scan_id)),
        artifact_path,
    )


def dataset_key(dataset_id: UUID, version_id: UUID, artifact_path: str) -> ObjectLocation:
    return _location(Bucket.DATASETS, "datasets", (str(dataset_id), str(version_id)), artifact_path)


def generated_site_key(
    project_id: UUID, site_version_id: UUID, artifact_path: str
) -> ObjectLocation:
    return _location(
        Bucket.GENERATED_SITES,
        "generated",
        (str(project_id), str(site_version_id)),
        artifact_path,
    )


def model_key(model_id: UUID, version_id: UUID, artifact_path: str) -> ObjectLocation:
    return _location(
        Bucket.MODEL_ARTIFACTS, "models", (str(model_id), str(version_id)), artifact_path
    )


def user_asset_key(project_id: UUID, asset_id: UUID, filename: str) -> ObjectLocation:
    return _location(
        Bucket.USER_ASSETS,
        "user-assets",
        (str(project_id), str(asset_id)),
        safe_filename(filename),
    )
