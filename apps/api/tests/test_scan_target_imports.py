"""Streaming scan-target normalization, validation, and commit tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi import FastAPI
from platform_api.auth.dependencies import current_user_dependency
from platform_api.errors import ApiError
from platform_api.persistence.models import (
    ScanCampaign,
    ScanTarget,
    ScanTargetImport,
    ScanTargetImportRow,
    User,
)
from platform_api.scans.dependencies import scan_target_import_service_dependency
from platform_api.scans.target_import_repositories import ScanTargetImportRepository
from platform_api.scans.target_import_service import ScanTargetImportService
from platform_api.scans.target_imports import (
    MAX_IMPORT_ROWS,
    TargetValidationError,
    normalize_import_target,
    parse_csv_rows,
    parse_text_rows,
)

NOW = datetime(2026, 7, 27, 16, 0, tzinfo=UTC)
pytestmark = pytest.mark.anyio


async def chunks(value: str, size: int = 7) -> AsyncIterator[bytes]:
    encoded = value.encode()
    for index in range(0, len(encoded), size):
        yield encoded[index : index + size]


class RecordingAudit:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def record(self, **values: Any) -> object:
        self.entries.append(values)
        return values


class FakeImportRepository:
    def __init__(self, campaign: ScanCampaign, owner_id: UUID) -> None:
        self.campaign = campaign
        self.owner_id = owner_id
        self.imports: dict[UUID, ScanTargetImport] = {}
        self.rows: list[ScanTargetImportRow] = []
        self.targets: list[ScanTarget] = []

    def add(self, entity: ScanTarget | ScanTargetImport | ScanTargetImportRow) -> None:
        self.add_all([entity])

    def add_all(
        self, entities: Sequence[ScanTarget | ScanTargetImport | ScanTargetImportRow]
    ) -> None:
        for entity in entities:
            if cast(UUID | None, entity.id) is None:
                entity.id = uuid4()
            if isinstance(entity, ScanTargetImport):
                self.imports[entity.id] = entity
            elif isinstance(entity, ScanTargetImportRow):
                self.rows.append(entity)
            else:
                self.targets.append(entity)

    async def flush(self) -> None:
        for target_import in self.imports.values():
            if cast(datetime | None, target_import.created_at) is None:
                target_import.created_at = NOW
                target_import.updated_at = NOW
                target_import.version = 1
        for row in self.rows:
            if cast(UUID | None, row.id) is None:
                row.id = uuid4()
            if cast(datetime | None, row.created_at) is None:
                row.created_at = NOW

    async def campaign_owned_for_update(
        self, campaign_id: UUID, project_id: UUID, owner_id: UUID
    ) -> ScanCampaign | None:
        if (
            self.campaign.id == campaign_id
            and self.campaign.project_id == project_id
            and self.owner_id == owner_id
        ):
            return self.campaign
        return None

    async def import_owned(
        self, import_id: UUID, campaign_id: UUID, project_id: UUID, owner_id: UUID
    ) -> ScanTargetImport | None:
        if (
            owner_id == self.owner_id
            and project_id == self.campaign.project_id
            and campaign_id == self.campaign.id
        ):
            return self.imports.get(import_id)
        return None

    async def existing_domains(self, campaign_id: UUID) -> set[str]:
        return {
            target.source_domain for target in self.targets if target.campaign_id == campaign_id
        }

    async def accepted_rows(
        self, import_id: UUID, *, after_row: int, limit: int
    ) -> tuple[ScanTargetImportRow, ...]:
        return tuple(
            row
            for row in self.rows
            if row.import_id == import_id
            and row.outcome == "accepted"
            and row.target_id is None
            and row.row_number > after_row
        )[:limit]

    async def error_rows(self, import_id: UUID) -> AsyncIterator[ScanTargetImportRow]:
        for row in self.rows:
            if row.import_id == import_id and row.outcome != "accepted":
                yield row


def fixture() -> tuple[ScanTargetImportService, FakeImportRepository, RecordingAudit, UUID, UUID]:
    owner_id = uuid4()
    project_id = uuid4()
    campaign = ScanCampaign(
        id=uuid4(),
        project_id=project_id,
        name="Import campaign",
        authorization_attested_at=NOW,
        status="draft",
    )
    repository = FakeImportRepository(campaign, owner_id)
    audit = RecordingAudit()
    return (
        ScanTargetImportService(cast(ScanTargetImportRepository, repository), audit),
        repository,
        audit,
        owner_id,
        project_id,
    )


def test_normalization_handles_unicode_punycode_trailing_dots_and_paths() -> None:
    unicode_target = normalize_import_target(
        "HTTPS://BÜCHER.example./accidental/path?q=1", allow_ip_literals=False
    )
    assert unicode_target.url == "https://xn--bcher-kva.example/"
    assert unicode_target.domain == "xn--bcher-kva.example"
    assert normalize_import_target("Example.COM/pricing", allow_ip_literals=False).url == (
        "https://example.com/"
    )


@pytest.mark.parametrize(
    ("value", "code", "blocked"),
    [
        ("ftp://example.com", "unsupported_scheme", False),
        (
            "https://user:password@example.com",  # pragma: allowlist secret
            "embedded_credentials",
            False,
        ),
        ("http://127.0.0.1", "non_public_ip", True),
        ("https://8.8.8.8", "ip_literal_requires_admin", True),
        ("https://co.uk", "invalid_public_suffix", False),
    ],
)
def test_normalization_has_typed_offline_failures(value: str, code: str, blocked: bool) -> None:
    with pytest.raises(TargetValidationError) as failure:
        normalize_import_target(value, allow_ip_literals=False)
    assert failure.value.code == code
    assert failure.value.blocked is blocked


async def test_text_parser_streams_at_least_twenty_thousand_rows() -> None:
    count = 0
    source = "".join(f"site-{number}.example\n" for number in range(20_000))
    async for row in parse_text_rows(chunks(source, 113)):
        count += 1
        assert row.row_number == count
    assert count == 20_000
    assert MAX_IMPORT_ROWS >= 20_000


async def test_csv_parser_preserves_source_rows_and_optional_metadata() -> None:
    source = 'domain,category,note\r\nexample.com,agency,"line one\nline two"\r\n'
    rows = [row async for row in parse_csv_rows(chunks(source, 3))]
    assert len(rows) == 1
    assert rows[0].row_number == 2
    assert rows[0].raw_value == "example.com"
    assert rows[0].metadata == {"category": "agency", "note": "line one\nline two"}


async def test_dry_run_classifies_rows_then_commits_only_accepted_domains() -> None:
    service, repository, audit, owner_id, project_id = fixture()
    repository.targets.append(
        ScanTarget(
            id=uuid4(),
            campaign_id=repository.campaign.id,
            url="https://present.example/",
            normalized_url="https://present.example/",
            source_domain="present.example",
            status="pending",
        )
    )
    result = await service.import_stream(
        project_id,
        repository.campaign.id,
        chunks(
            "example.com/path\nEXAMPLE.com\npresent.example\n127.0.0.1\nhttps://u:p@example.net\n"
        ),
        source_type="paste",
        filename=None,
        media_type="text/plain",
        dry_run=True,
        authorization_attested=True,
        allow_ip_literals=False,
        owner_id=owner_id,
        request_id="request-1",
    )
    assert (result.accepted_count, result.duplicate_count) == (1, 1)
    assert (result.already_present_count, result.blocked_count, result.invalid_count) == (1, 1, 1)
    assert result.processed_rows == 5
    assert len(repository.targets) == 1

    committed = await service.commit(
        project_id,
        repository.campaign.id,
        result.id,
        expected_version=result.version,
        authorization_attested=True,
        owner_id=owner_id,
        request_id="request-2",
    )
    assert committed.status == "committed"
    assert committed.committed_count == 1
    assert len(repository.targets) == 2
    assert repository.targets[-1].import_row_number == 1
    assert repository.targets[-1].import_metadata == {}
    assert [entry["action"] for entry in audit.entries] == [
        "scan_campaign.targets_imported",
        "scan_campaign.target_import_committed",
    ]


async def test_import_requires_attestation_and_hides_unowned_campaign() -> None:
    service, repository, _, owner_id, project_id = fixture()
    with pytest.raises(ApiError) as unattested:
        await service.import_stream(
            project_id,
            repository.campaign.id,
            chunks("example.com\n"),
            source_type="paste",
            filename=None,
            media_type="text/plain",
            dry_run=True,
            authorization_attested=False,
            allow_ip_literals=False,
            owner_id=owner_id,
            request_id="request-1",
        )
    assert unattested.value.code == "crawl_authorization_attestation_required"

    with pytest.raises(ApiError) as hidden:
        await service.get(project_id, repository.campaign.id, uuid4(), owner_id=uuid4())
    assert hidden.value.code == "scan_target_import_not_found"


async def test_raw_import_api_streams_validation_and_csv_error_export(app: FastAPI) -> None:
    service, repository, _, owner_id, project_id = fixture()
    user = User(
        id=owner_id,
        email="owner@example.test",
        display_name="Owner",
        status="active",
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )

    async def override_user() -> User:
        return user

    async def override_service() -> ScanTargetImportService:
        return service

    app.dependency_overrides[current_user_dependency] = override_user
    app.dependency_overrides[scan_target_import_service_dependency] = override_service
    base = f"/api/v1/projects/{project_id}/scan-campaigns/{repository.campaign.id}/target-imports"
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        forbidden = await client.post(
            base,
            params={
                "source_type": "paste",
                "authorization_attested": "true",
                "allow_ip_literals": "true",
            },
            content="8.8.8.8\n",
            headers={"Content-Type": "text/plain"},
        )
        validated = await client.post(
            base,
            params={"source_type": "paste", "authorization_attested": "true"},
            content="example.com\nexample.com\n",
            headers={"Content-Type": "text/plain"},
        )
        export = await client.get(f"{base}/{validated.json()['id']}/errors.csv")

    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "administrator_required"
    assert validated.status_code == 201
    assert validated.json()["accepted_count"] == 1
    assert validated.json()["duplicate_count"] == 1
    assert export.status_code == 200
    assert "2,example.com,duplicate,duplicate_in_import" in export.text
