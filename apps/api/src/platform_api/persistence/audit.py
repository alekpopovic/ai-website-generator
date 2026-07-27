"""Append-only audit recording service."""

from __future__ import annotations

from uuid import UUID

from platform_api.persistence.json import JsonValue, normalize_json_value
from platform_api.persistence.models import AuditLog
from platform_api.persistence.repositories import AuditLogRepository


class AuditLogService:
    """Create audit records inside the caller's current transaction."""

    def __init__(self, repository: AuditLogRepository) -> None:
        self._repository = repository

    def record(
        self,
        *,
        action: str,
        resource_type: str,
        actor_user_id: UUID | None = None,
        resource_id: UUID | None = None,
        request_id: str | None = None,
        details: object | None = None,
    ) -> AuditLog:
        """Validate and stage one audit record without committing independently."""
        normalized: JsonValue = {} if details is None else normalize_json_value(details)
        entry = AuditLog(
            action=action,
            resource_type=resource_type,
            actor_user_id=actor_user_id,
            resource_id=resource_id,
            request_id=request_id,
            details=normalized,
        )
        self._repository.add(entry)
        return entry
