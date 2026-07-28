"""Artifact ownership, safe reads, retention, and removal-request orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from platform_clients.object_storage.models import (
    Bucket,
    ChecksumMismatchError,
    ObjectLocation,
    ObjectNotFoundError,
    ObjectStorage,
)
from platform_clients.object_storage.scan_artifacts import (
    SCREENSHOT_ARTIFACT_KINDS,
    SENSITIVE_ARTIFACT_KINDS,
    ArtifactProvenanceStatus,
    ArtifactRetentionStatus,
    ScanArtifactKind,
)
from platform_workflows.commands import CompactWorkflowInput
from platform_workflows.dispatcher import WorkflowDispatcher
from platform_workflows.identifiers import WorkflowKind, workflow_id

from platform_api.artifacts.schemas import (
    ArtifactRemovalRequest,
    PresignedArtifactReadResponse,
    ScanArtifactResponse,
)
from platform_api.dependencies import AfterCommitActions
from platform_api.errors import ApiError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.models import ScanArtifact


class ArtifactRepository(Protocol):
    async def owned(
        self,
        artifact_id: UUID,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> ScanArtifact | None: ...

    async def list_for_page(
        self,
        page_id: UUID,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
    ) -> tuple[ScanArtifact, ...] | None: ...

    async def flush(self) -> None: ...


@dataclass(frozen=True, slots=True)
class AuthorizedScreenshot:
    artifact: ScanArtifact
    location: ObjectLocation


class ScanArtifactService:
    def __init__(
        self,
        repository: ArtifactRepository,
        storage: ObjectStorage,
        audit: AuditLogService,
        dispatcher: WorkflowDispatcher,
        after_commit: AfterCommitActions,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._audit = audit
        self._dispatcher = dispatcher
        self._after_commit = after_commit

    async def list_for_page(
        self, project_id: UUID, campaign_id: UUID, page_id: UUID, *, owner_id: UUID
    ) -> tuple[ScanArtifactResponse, ...]:
        artifacts = await self._repository.list_for_page(page_id, campaign_id, project_id, owner_id)
        if artifacts is None:
            raise ApiError(404, "scan_page_not_found", "The scan page was not found.")
        return tuple(ScanArtifactResponse.model_validate(item) for item in artifacts)

    async def presign_read(
        self,
        project_id: UUID,
        campaign_id: UUID,
        artifact_id: UUID,
        *,
        owner_id: UUID,
        administrator: bool,
        expires_seconds: int,
    ) -> PresignedArtifactReadResponse:
        artifact = await self._require_readable(
            project_id, campaign_id, artifact_id, owner_id=owner_id
        )
        kind = ScanArtifactKind(artifact.artifact_type)
        if kind in SENSITIVE_ARTIFACT_KINDS and not administrator:
            raise ApiError(
                403,
                "raw_scan_artifact_restricted",
                "Raw and rendered HTML artifacts require administrator access.",
            )
        try:
            url = await self._storage.presign_read(
                _location(artifact), expires_seconds=expires_seconds
            )
        except ObjectNotFoundError as error:
            raise ApiError(
                404, "scan_artifact_object_not_found", "The scan artifact object was not found."
            ) from error
        return PresignedArtifactReadResponse(
            artifact_id=artifact.id,
            url=url,
            expires_seconds=expires_seconds,
        )

    async def authorize_screenshot(
        self,
        project_id: UUID,
        campaign_id: UUID,
        artifact_id: UUID,
        *,
        owner_id: UUID,
    ) -> AuthorizedScreenshot:
        artifact = await self._require_readable(
            project_id, campaign_id, artifact_id, owner_id=owner_id
        )
        if (
            ScanArtifactKind(artifact.artifact_type) not in SCREENSHOT_ARTIFACT_KINDS
            or artifact.content_type != "image/png"
            or artifact.content_encoding is not None
        ):
            raise ApiError(
                404, "scan_screenshot_not_found", "The requested safe screenshot was not found."
            )
        location = _location(artifact)
        try:
            stored = await self._storage.stat(location)
        except ChecksumMismatchError as error:
            raise ApiError(
                409,
                "scan_artifact_integrity_mismatch",
                "The screenshot metadata did not pass integrity validation.",
            ) from error
        if stored is None:
            raise ApiError(
                404, "scan_artifact_object_not_found", "The scan artifact object was not found."
            )
        if stored.sha256 != artifact.sha256 or stored.content_type != "image/png":
            raise ApiError(
                409,
                "scan_artifact_integrity_mismatch",
                "The screenshot metadata did not pass integrity validation.",
            )
        return AuthorizedScreenshot(artifact=artifact, location=location)

    async def request_removal(
        self,
        project_id: UUID,
        campaign_id: UUID,
        artifact_id: UUID,
        payload: ArtifactRemovalRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> ScanArtifactResponse:
        artifact = await self._repository.owned(
            artifact_id,
            campaign_id,
            project_id,
            owner_id,
            for_update=True,
        )
        if artifact is None:
            raise ApiError(404, "scan_artifact_not_found", "The scan artifact was not found.")
        if artifact.retention_status == ArtifactRetentionStatus.LEGAL_HOLD.value:
            raise ApiError(
                409,
                "scan_artifact_legal_hold",
                "The scan artifact is subject to a legal hold and cannot be removed.",
            )
        if artifact.retention_status == ArtifactRetentionStatus.DELETED.value:
            raise ApiError(409, "scan_artifact_deleted", "The scan artifact is already deleted.")
        deletion_workflow_id = workflow_id(
            WorkflowKind.ARTIFACT_DELETION, artifact.id, payload.idempotency_key
        )
        artifact.retention_status = ArtifactRetentionStatus.PENDING_DELETION.value
        artifact.provenance_status = ArtifactProvenanceStatus.REMOVAL_PENDING.value
        artifact.deletion_requested_at = datetime.now(UTC)
        artifact.deletion_requested_by_user_id = owner_id
        artifact.deletion_reason = " ".join(payload.reason.split())[:500]
        artifact.deletion_workflow_id = deletion_workflow_id
        self._audit.record(
            action="scan_artifact.removal_requested",
            resource_type="scan_artifact",
            resource_id=artifact.id,
            actor_user_id=owner_id,
            request_id=request_id,
            details={
                "campaign_id": str(campaign_id),
                "artifact_type": artifact.artifact_type,
                "workflow_id": deletion_workflow_id,
            },
        )
        await self._repository.flush()
        command = CompactWorkflowInput(
            job_id=str(artifact.id),
            project_id=str(project_id),
            requested_by_user_id=str(owner_id),
            idempotency_key=payload.idempotency_key,
            input_object_key=artifact.object_key,
        )
        self._after_commit.add(
            "dispatch-artifact-deletion-placeholder",
            _dispatch(self._dispatcher, command),
        )
        return ScanArtifactResponse.model_validate(artifact)

    async def _require_readable(
        self,
        project_id: UUID,
        campaign_id: UUID,
        artifact_id: UUID,
        *,
        owner_id: UUID,
    ) -> ScanArtifact:
        artifact = await self._repository.owned(artifact_id, campaign_id, project_id, owner_id)
        if artifact is None:
            raise ApiError(404, "scan_artifact_not_found", "The scan artifact was not found.")
        if artifact.retention_status not in {
            ArtifactRetentionStatus.ACTIVE.value,
            ArtifactRetentionStatus.LEGAL_HOLD.value,
        }:
            raise ApiError(
                410, "scan_artifact_unavailable", "The scan artifact is no longer readable."
            )
        return artifact


def _location(artifact: ScanArtifact) -> ObjectLocation:
    return ObjectLocation(Bucket(artifact.bucket), artifact.object_key)


def _dispatch(
    dispatcher: WorkflowDispatcher, command: CompactWorkflowInput
) -> Callable[[], Awaitable[None]]:
    async def callback() -> None:
        await dispatcher.dispatch(WorkflowKind.ARTIFACT_DELETION, command)

    return callback
