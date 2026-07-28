"""Artifact ownership, safe-read, retention, and removal placeholder tests."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx2
import pytest
from platform_api.artifacts.dependencies import scan_artifact_service_dependency
from platform_api.artifacts.schemas import ArtifactRemovalRequest
from platform_api.artifacts.service import ScanArtifactService
from platform_api.auth.dependencies import current_user_dependency
from platform_api.dependencies import AfterCommitActions, object_storage_dependency
from platform_api.errors import ApiError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.models import AuditLog, ScanArtifact, User
from platform_api.testing import create_test_app
from platform_clients.object_storage.fake import InMemoryObjectStorage
from platform_clients.object_storage.keys import scan_key
from platform_clients.object_storage.models import (
    Bucket,
    ObjectLocation,
    RetentionMetadata,
    UploadRequest,
)
from platform_clients.object_storage.scan_artifacts import ScanArtifactKind
from platform_workflows.dispatcher import FakeWorkflowDispatcher
from platform_workflows.identifiers import WorkflowKind

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


class FakeArtifactRepository:
    def __init__(self, artifact: ScanArtifact, *, owner_id: UUID) -> None:
        self.artifact = artifact
        self.owner_id = owner_id

    async def owned(
        self,
        artifact_id: UUID,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> ScanArtifact | None:
        del for_update
        if (
            artifact_id == self.artifact.id
            and campaign_id == self.artifact.campaign_id
            and project_id == self.artifact.project_id
            and owner_id == self.owner_id
        ):
            return self.artifact
        return None

    async def list_for_page(
        self,
        page_id: UUID,
        campaign_id: UUID,
        project_id: UUID,
        owner_id: UUID,
    ) -> tuple[ScanArtifact, ...] | None:
        if (
            page_id == self.artifact.crawl_page_id
            and campaign_id == self.artifact.campaign_id
            and project_id == self.artifact.project_id
            and owner_id == self.owner_id
        ):
            return (self.artifact,)
        return None

    async def flush(self) -> None:
        return None


class RecordingAuditRepository:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    def add(self, entry: AuditLog) -> None:
        self.entries.append(entry)


async def chunks(body: bytes) -> AsyncIterator[bytes]:
    yield body


async def fixture(
    kind: ScanArtifactKind,
) -> tuple[
    ScanArtifactService,
    ScanArtifact,
    UUID,
    InMemoryObjectStorage,
    FakeWorkflowDispatcher,
    AfterCommitActions,
    RecordingAuditRepository,
]:
    owner_id, project_id, campaign_id = uuid4(), uuid4(), uuid4()
    target_id, page_id, page_scan_id = uuid4(), uuid4(), uuid4()
    artifact_id = uuid4()
    is_screenshot = "screenshot" in kind.value
    is_raw = kind in {ScanArtifactKind.RAW_RESPONSE_HTML, ScanArtifactKind.RENDERED_HTML}
    body = (
        b"\x89PNG\r\nfixture"
        if is_screenshot
        else b"<html>private</html>"
        if is_raw
        else b'{"fixture":true}'
    )
    content_type = "image/png" if is_screenshot else "text/html" if is_raw else "application/json"
    location = scan_key(target_id, page_scan_id, f"{kind.value}-{artifact_id}.bin")
    digest = hashlib.sha256(body).hexdigest()
    storage = InMemoryObjectStorage()
    stored = await storage.upload(
        location,
        chunks(body),
        UploadRequest(
            expected_sha256=digest,
            content_type=content_type,
            retention=RetentionMetadata(
                policy="scan-campaign", retain_until=NOW + timedelta(days=30)
            ),
        ),
    )
    artifact = ScanArtifact(
        id=artifact_id,
        project_id=project_id,
        campaign_id=campaign_id,
        source_website_id=target_id,
        crawl_page_id=page_id,
        page_scan_id=page_scan_id,
        artifact_type=kind.value,
        bucket=stored.location.bucket.value,
        object_key=stored.location.key,
        sha256=stored.sha256,
        size_bytes=stored.size,
        content_type=content_type,
        content_encoding=None,
        source_url="https://fixture.example/source",
        final_url="https://fixture.example/final",
        scan_timestamp=NOW,
        scanner_version="fixture/1",
        viewport="desktop" if is_screenshot else None,
        provenance_status="authorized",
        access_policy=(
            "safe_screenshot" if is_screenshot else "restricted_raw" if is_raw else "project_member"
        ),
        retention_policy="scan-campaign",
        retention_status="active",
        retain_until=NOW + timedelta(days=30),
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )
    dispatcher = FakeWorkflowDispatcher()
    after_commit = AfterCommitActions()
    audits = RecordingAuditRepository()
    service = ScanArtifactService(
        FakeArtifactRepository(artifact, owner_id=owner_id),
        storage,
        AuditLogService(audits),
        dispatcher,
        after_commit,
    )
    return service, artifact, owner_id, storage, dispatcher, after_commit, audits


@pytest.mark.anyio
async def test_raw_html_presign_is_administrator_only() -> None:
    service, artifact, owner_id, _, _, _, _ = await fixture(ScanArtifactKind.RAW_RESPONSE_HTML)
    with pytest.raises(ApiError) as denied:
        await service.presign_read(
            artifact.project_id,
            artifact.campaign_id,
            artifact.id,
            owner_id=owner_id,
            administrator=False,
            expires_seconds=300,
        )
    assert denied.value.status_code == 403

    signed = await service.presign_read(
        artifact.project_id,
        artifact.campaign_id,
        artifact.id,
        owner_id=owner_id,
        administrator=True,
        expires_seconds=300,
    )
    assert signed.artifact_id == artifact.id
    assert "operation=read" in signed.url


@pytest.mark.anyio
async def test_screenshot_authorization_checks_type_and_object_integrity() -> None:
    service, artifact, owner_id, storage, _, _, _ = await fixture(
        ScanArtifactKind.DESKTOP_SCREENSHOT
    )
    screenshot = await service.authorize_screenshot(
        artifact.project_id, artifact.campaign_id, artifact.id, owner_id=owner_id
    )
    body = b"".join(
        [
            chunk
            async for chunk in storage.stream_download(
                screenshot.location, expected_sha256=artifact.sha256
            )
        ]
    )
    assert body.startswith(b"\x89PNG")


@pytest.mark.anyio
async def test_screenshot_endpoint_proxies_png_with_safe_headers() -> None:
    service, artifact, owner_id, storage, _, _, _ = await fixture(
        ScanArtifactKind.DESKTOP_SCREENSHOT
    )
    user = User(
        id=owner_id,
        email="artifact-owner@local.test",
        display_name="Artifact Owner",
        status="active",
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )

    async def current_user() -> User:
        return user

    async def artifact_service() -> ScanArtifactService:
        return service

    async def object_storage() -> InMemoryObjectStorage:
        return storage

    app = create_test_app(
        dependency_overrides={
            current_user_dependency: current_user,
            scan_artifact_service_dependency: artifact_service,
            object_storage_dependency: object_storage,
        }
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        response = await client.get(
            f"/api/v1/projects/{artifact.project_id}/scan-campaigns/"
            f"{artifact.campaign_id}/artifacts/{artifact.id}/screenshot"
        )

    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.anyio
async def test_removal_request_marks_pending_and_dispatches_only_a_placeholder() -> None:
    service, artifact, owner_id, storage, dispatcher, after_commit, audits = await fixture(
        ScanArtifactKind.STYLE_SUMMARY
    )
    response = await service.request_removal(
        artifact.project_id,
        artifact.campaign_id,
        artifact.id,
        ArtifactRemovalRequest(reason="Source removal request", idempotency_key="removal-001"),
        owner_id=owner_id,
        request_id="request-001",
    )

    assert response.retention_status == "pending_deletion"
    assert (
        await storage.stat(ObjectLocation(Bucket(artifact.bucket), artifact.object_key)) is not None
    )
    assert not dispatcher.dispatched
    await after_commit.run()
    assert dispatcher.dispatched[0][0] is WorkflowKind.ARTIFACT_DELETION
    assert audits.entries[0].action == "scan_artifact.removal_requested"
