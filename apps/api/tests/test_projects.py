"""Project-domain authorization, lifecycle, and API contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi import FastAPI
from platform_api.auth.dependencies import current_user_dependency
from platform_api.errors import ApiError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.models import AuditLog, Project, User
from platform_api.persistence.pagination import Page
from platform_api.projects.dependencies import project_service_dependency
from platform_api.projects.schemas import (
    ProjectCreateRequest,
    ProjectListParams,
    ProjectResponse,
    ProjectUpdateRequest,
)
from platform_api.projects.service import ProjectService

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


class FakeProjectRepository:
    """Owner-scoped in-memory project repository."""

    def __init__(self) -> None:
        self.projects: dict[UUID, Project] = {}
        self._new: set[UUID] = set()

    def add(self, entity: Project) -> None:
        entity.id = uuid4()
        entity.created_at = NOW
        entity.updated_at = NOW
        entity.version = 1
        self.projects[entity.id] = entity
        self._new.add(entity.id)

    async def flush(self) -> None:
        if self._new:
            self._new.clear()
            return
        for project in self.projects.values():
            project.version += 1

    async def owned(
        self, project_id: UUID, owner_id: UUID, *, for_update: bool = False
    ) -> Project | None:
        del for_update
        project = self.projects.get(project_id)
        return project if project is not None and project.owner_id == owner_id else None

    async def slug_exists(
        self, owner_id: UUID, slug: str, *, exclude_id: UUID | None = None
    ) -> bool:
        return any(
            project.owner_id == owner_id and project.slug == slug and project.id != exclude_id
            for project in self.projects.values()
        )

    async def owned_page(
        self,
        *,
        owner_id: UUID,
        limit: int,
        offset: int,
        search: str | None,
        status: str | None,
        sort_by: str,
        sort_order: str,
    ) -> Page[Project]:
        projects = [project for project in self.projects.values() if project.owner_id == owner_id]
        if search:
            projects = [project for project in projects if search.lower() in project.name.lower()]
        if status:
            projects = [project for project in projects if project.status == status]
        projects.sort(key=lambda project: getattr(project, sort_by), reverse=sort_order == "desc")
        return Page(
            items=tuple(projects[offset : offset + limit]),
            total=len(projects),
            limit=limit,
            offset=offset,
        )


class RecordingAuditRepository:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    def add(self, entry: AuditLog) -> None:
        self.entries.append(entry)


def service_fixture() -> tuple[ProjectService, FakeProjectRepository, RecordingAuditRepository]:
    repository = FakeProjectRepository()
    audits = RecordingAuditRepository()
    return ProjectService(repository, AuditLogService(audits)), repository, audits


@pytest.mark.anyio
async def test_create_generates_unique_owner_scoped_slugs_and_audit_events() -> None:
    service, _, audits = service_fixture()
    owner_id = uuid4()
    payload = ProjectCreateRequest(name="Café Website", settings={"theme": "calm"})

    first = await service.create(payload, owner_id=owner_id, request_id="request-1")
    second = await service.create(payload, owner_id=owner_id, request_id="request-2")

    assert first.slug == "cafe-website"
    assert second.slug == "cafe-website-2"
    assert first.owner_id == owner_id
    assert first.settings == {"theme": "calm"}
    assert [entry.action for entry in audits.entries] == ["project.created", "project.created"]


@pytest.mark.anyio
async def test_project_reads_never_reveal_another_owners_resource() -> None:
    service, _, _ = service_fixture()
    project = await service.create(
        ProjectCreateRequest(name="Private"), owner_id=uuid4(), request_id="request-create"
    )

    with pytest.raises(ApiError) as hidden:
        await service.get(project.id, owner_id=uuid4())

    assert hidden.value.status_code == 404
    assert hidden.value.code == "project_not_found"


@pytest.mark.anyio
async def test_update_requires_current_version_and_records_changed_fields() -> None:
    service, _, audits = service_fixture()
    owner_id = uuid4()
    project = await service.create(
        ProjectCreateRequest(name="Original"), owner_id=owner_id, request_id="request-create"
    )

    updated = await service.update(
        project.id,
        ProjectUpdateRequest(version=project.version, name="Updated", default_industry="Travel"),
        owner_id=owner_id,
        request_id="request-update",
    )
    assert updated.name == "Updated"
    assert updated.version == project.version + 1
    assert audits.entries[-1].details == {"changed_fields": ["default_industry", "name"]}

    with pytest.raises(ApiError) as conflict:
        await service.update(
            project.id,
            ProjectUpdateRequest(version=project.version, name="Stale"),
            owner_id=owner_id,
            request_id="request-stale",
        )
    assert conflict.value.code == "project_version_conflict"


@pytest.mark.anyio
async def test_archive_and_restore_replace_destructive_deletion() -> None:
    service, _, audits = service_fixture()
    owner_id = uuid4()
    project = await service.create(
        ProjectCreateRequest(name="Lifecycle"), owner_id=owner_id, request_id="request-create"
    )

    archived = await service.archive(
        project.id, version=project.version, owner_id=owner_id, request_id="request-archive"
    )
    restored = await service.restore(
        project.id, version=archived.version, owner_id=owner_id, request_id="request-restore"
    )

    assert archived.status == "archived"
    assert restored.status == "draft"
    assert [entry.action for entry in audits.entries[-2:]] == [
        "project.archived",
        "project.restored",
    ]


@pytest.mark.anyio
async def test_list_search_filter_sort_and_pagination_are_owner_scoped() -> None:
    service, _, _ = service_fixture()
    owner_id = uuid4()
    for name in ("Alpha", "Beta", "Alpha Two"):
        await service.create(
            ProjectCreateRequest(name=name), owner_id=owner_id, request_id=f"request-{name}"
        )
    await service.create(
        ProjectCreateRequest(name="Alpha Foreign"),
        owner_id=uuid4(),
        request_id="request-foreign",
    )

    page = await service.list(
        owner_id=owner_id,
        params=ProjectListParams(search="Alpha", sort_by="name", sort_order="asc", limit=1),
    )

    assert page.total == 2
    assert [project.name for project in page.items] == ["Alpha"]


@pytest.mark.anyio
async def test_project_routes_require_owner_and_return_typed_page(app: FastAPI) -> None:
    owner = User(
        id=uuid4(),
        email="owner@example.test",
        display_name="Owner",
        status="active",
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )
    project = ProjectResponse(
        id=uuid4(),
        owner_id=owner.id,
        name="API Project",
        slug="api-project",
        description=None,
        default_language="en",
        default_industry=None,
        status="draft",
        settings={},
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )

    class StubService:
        async def list(self, *, owner_id: UUID, params: ProjectListParams) -> Page[ProjectResponse]:
            assert owner_id == owner.id
            return Page(items=(project,), total=1, limit=params.limit, offset=params.offset)

    async def override_user() -> User:
        return owner

    async def override_service() -> StubService:
        return StubService()

    app.dependency_overrides[current_user_dependency] = override_user
    app.dependency_overrides[project_service_dependency] = override_service
    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        response = await client.get("/api/v1/projects", params={"limit": 10})

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == str(project.id)
    assert response.json()["pagination"] == {
        "offset": 0,
        "limit": 10,
        "total": 1,
        "has_more": False,
    }
    assert "delete" not in app.openapi()["paths"]["/api/v1/projects/{project_id}"]
