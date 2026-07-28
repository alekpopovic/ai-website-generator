"""Explicit sequential migration registry for persisted WebsiteProfile payloads."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from platform_schemas.analysis import ANALYSIS_SCHEMA_VERSION, WebsiteProfile

WebsiteProfileMigration = Callable[[dict[str, Any]], dict[str, Any]]
_MIGRATIONS: dict[int, WebsiteProfileMigration] = {}


def register_website_profile_migration(
    source_version: int, migration: WebsiteProfileMigration
) -> None:
    """Register one forward migration from `source_version` to the next integer version."""

    if source_version < 1 or source_version in _MIGRATIONS:
        raise ValueError("website profile migration source version is invalid or registered")
    _MIGRATIONS[source_version] = migration


def migrate_website_profile(
    payload: Mapping[str, Any], *, target_version: int = ANALYSIS_SCHEMA_VERSION
) -> WebsiteProfile:
    """Migrate a copied payload sequentially, then validate the complete target contract."""

    current = deepcopy(dict(payload))
    source_version = current.get("schema_version")
    if not isinstance(source_version, int) or isinstance(source_version, bool):
        raise ValueError("website profile schema_version must be an integer")
    if target_version != ANALYSIS_SCHEMA_VERSION:
        raise ValueError("target website profile schema version is not supported by this build")
    if source_version > target_version:
        raise ValueError("future website profile versions cannot be downgraded")
    while source_version < target_version:
        migration = _MIGRATIONS.get(source_version)
        if migration is None:
            raise ValueError(
                f"no website profile migration registered for version {source_version}"
            )
        migrated = migration(deepcopy(current))
        expected = source_version + 1
        if migrated.get("schema_version") != expected:
            raise ValueError("website profile migration did not advance exactly one version")
        current = migrated
        source_version = expected
    return WebsiteProfile.model_validate(current)
