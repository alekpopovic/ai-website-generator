"""Ownership, attestation, validation, and batch commit rules for target imports."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Protocol
from uuid import UUID, uuid4

from platform_api.errors import ApiError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.models import (
    ScanCampaign,
    ScanTarget,
    ScanTargetImport,
    ScanTargetImportRow,
)
from platform_api.scans.schemas import ScanTargetImportResponse, TargetImportSource
from platform_api.scans.target_import_repositories import ScanTargetImportRepository
from platform_api.scans.target_imports import (
    ImportSourceRow,
    TargetValidationError,
    normalize_import_target,
    parse_csv_rows,
    parse_text_rows,
    sanitize_filename,
)

_BATCH_SIZE = 500


class ImportAudit(Protocol):
    def record(
        self,
        *,
        action: str,
        resource_type: str,
        actor_user_id: UUID | None,
        resource_id: UUID | None,
        request_id: str | None,
        details: dict[str, object] | None = None,
    ) -> object: ...


class ScanTargetImportService:
    def __init__(
        self, repository: ScanTargetImportRepository, audit: AuditLogService | ImportAudit
    ) -> None:
        self._repository = repository
        self._audit = audit

    async def import_stream(
        self,
        project_id: UUID,
        campaign_id: UUID,
        chunks: AsyncIterable[bytes],
        *,
        source_type: TargetImportSource,
        filename: str | None,
        media_type: str,
        dry_run: bool,
        authorization_attested: bool,
        allow_ip_literals: bool,
        owner_id: UUID,
        request_id: str,
    ) -> ScanTargetImportResponse:
        if not authorization_attested:
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "crawl_authorization_attestation_required",
                "Confirm that you are authorized to crawl every submitted target.",
            )
        campaign = await self._campaign(project_id, campaign_id, owner_id)
        now = datetime.now(UTC)
        campaign.authorization_attested_at = now
        target_import = ScanTargetImport(
            campaign_id=campaign.id,
            requested_by_user_id=owner_id,
            source_type=source_type,
            filename=sanitize_filename(filename),
            media_type=media_type[:100],
            dry_run=dry_run,
            authorization_attested_at=now,
            allow_ip_literals=allow_ip_literals,
            status="validating",
            total_rows=0,
            processed_rows=0,
            accepted_count=0,
            duplicate_count=0,
            invalid_count=0,
            blocked_count=0,
            already_present_count=0,
            committed_count=0,
        )
        self._repository.add(target_import)
        await self._repository.flush()
        existing = await self._repository.existing_domains(campaign.id)
        seen: set[str] = set()
        pending: list[ScanTarget | ScanTargetImportRow] = []
        rows = parse_csv_rows(chunks) if source_type == "csv" else parse_text_rows(chunks)

        try:
            async for source in rows:
                row, target = self._evaluate_row(
                    source,
                    target_import=target_import,
                    campaign=campaign,
                    seen=seen,
                    existing=existing,
                    allow_ip_literals=allow_ip_literals,
                    commit=not dry_run,
                )
                pending.append(row)
                if target is not None:
                    pending.append(target)
                    row.target_id = target.id
                    target_import.committed_count += 1
                target_import.total_rows += 1
                target_import.processed_rows += 1
                if len(pending) >= _BATCH_SIZE:
                    self._repository.add_all(pending)
                    pending.clear()
                    await self._repository.flush()
        except TargetValidationError as error:
            target_import.status = "failed"
            await self._repository.flush()
            error_status = (
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE
                if error.code in {"file_too_large", "row_limit_exceeded"}
                else HTTPStatus.UNPROCESSABLE_ENTITY
            )
            raise ApiError(error_status, error.code, error.message) from error

        if pending:
            self._repository.add_all(pending)
        target_import.status = "completed" if dry_run else "committed"
        if not dry_run:
            target_import.committed_at = now
        await self._repository.flush()
        self._audit.record(
            action="scan_campaign.targets_imported",
            resource_type="scan_target_import",
            actor_user_id=owner_id,
            resource_id=target_import.id,
            request_id=request_id,
            details={
                "campaign_id": campaign.id,
                "dry_run": dry_run,
                "processed_rows": target_import.processed_rows,
                "accepted_count": target_import.accepted_count,
                "committed_count": target_import.committed_count,
            },
        )
        return ScanTargetImportResponse.model_validate(target_import)

    async def get(
        self, project_id: UUID, campaign_id: UUID, import_id: UUID, *, owner_id: UUID
    ) -> ScanTargetImportResponse:
        return ScanTargetImportResponse.model_validate(
            await self._owned_import(project_id, campaign_id, import_id, owner_id)
        )

    async def commit(
        self,
        project_id: UUID,
        campaign_id: UUID,
        import_id: UUID,
        *,
        expected_version: int,
        authorization_attested: bool,
        owner_id: UUID,
        request_id: str,
    ) -> ScanTargetImportResponse:
        if not authorization_attested:
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "crawl_authorization_attestation_required",
                "Confirm authorization again before committing the import.",
            )
        campaign = await self._campaign(project_id, campaign_id, owner_id)
        target_import = await self._owned_import(project_id, campaign_id, import_id, owner_id)
        if target_import.version != expected_version:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "scan_target_import_version_conflict",
                "The import changed since it was loaded.",
            )
        if not target_import.dry_run or target_import.status != "completed":
            raise ApiError(
                HTTPStatus.CONFLICT,
                "scan_target_import_not_committable",
                "Only a completed dry-run import can be committed.",
            )
        existing = await self._repository.existing_domains(campaign.id)
        after_row = 0
        committed = 0
        while True:
            rows = await self._repository.accepted_rows(
                target_import.id, after_row=after_row, limit=_BATCH_SIZE
            )
            if not rows:
                break
            targets: list[ScanTarget] = []
            for row in rows:
                after_row = row.row_number
                if row.source_domain is None or row.normalized_url is None:
                    continue
                if row.source_domain in existing:
                    row.outcome = "already_present"
                    row.reason_code = "already_present"
                    row.reason_message = "Domain was added after this dry run."
                    target_import.accepted_count -= 1
                    target_import.already_present_count += 1
                    continue
                target = self._target(campaign.id, target_import.id, row)
                targets.append(target)
                row.target_id = target.id
                existing.add(row.source_domain)
                committed += 1
            if targets:
                self._repository.add_all(targets)
            await self._repository.flush()
        now = datetime.now(UTC)
        campaign.authorization_attested_at = now
        target_import.status = "committed"
        target_import.committed_count = committed
        target_import.committed_at = now
        await self._repository.flush()
        self._audit.record(
            action="scan_campaign.target_import_committed",
            resource_type="scan_target_import",
            actor_user_id=owner_id,
            resource_id=target_import.id,
            request_id=request_id,
            details={"campaign_id": campaign.id, "committed_count": committed},
        )
        return ScanTargetImportResponse.model_validate(target_import)

    async def error_rows(
        self, project_id: UUID, campaign_id: UUID, import_id: UUID, *, owner_id: UUID
    ) -> AsyncIterator[ScanTargetImportRow]:
        await self._owned_import(project_id, campaign_id, import_id, owner_id)
        async for row in self._repository.error_rows(import_id):
            yield row

    async def _campaign(self, project_id: UUID, campaign_id: UUID, owner_id: UUID) -> ScanCampaign:
        campaign = await self._repository.campaign_owned_for_update(
            campaign_id, project_id, owner_id
        )
        if campaign is None:
            raise ApiError(
                HTTPStatus.NOT_FOUND, "scan_campaign_not_found", "Scan campaign was not found."
            )
        if campaign.status != "draft":
            raise ApiError(
                HTTPStatus.CONFLICT,
                "invalid_scan_campaign_transition",
                "Targets can only be imported into draft campaigns.",
            )
        return campaign

    async def _owned_import(
        self, project_id: UUID, campaign_id: UUID, import_id: UUID, owner_id: UUID
    ) -> ScanTargetImport:
        target_import = await self._repository.import_owned(
            import_id, campaign_id, project_id, owner_id
        )
        if target_import is None:
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                "scan_target_import_not_found",
                "Scan target import was not found.",
            )
        return target_import

    @staticmethod
    def _evaluate_row(
        source: ImportSourceRow,
        *,
        target_import: ScanTargetImport,
        campaign: ScanCampaign,
        seen: set[str],
        existing: set[str],
        allow_ip_literals: bool,
        commit: bool,
    ) -> tuple[ScanTargetImportRow, ScanTarget | None]:
        error = source.validation_error
        normalized = None
        if error is None:
            try:
                normalized = normalize_import_target(
                    source.raw_value, allow_ip_literals=allow_ip_literals
                )
            except TargetValidationError as validation_error:
                error = validation_error
        if error is not None:
            outcome = "blocked" if error.blocked else "invalid"
            setattr(
                target_import, f"{outcome}_count", getattr(target_import, f"{outcome}_count") + 1
            )
            return (
                ScanTargetImportRow(
                    import_id=target_import.id,
                    row_number=source.row_number,
                    raw_value=source.raw_value[:2_048],
                    row_metadata=source.metadata,
                    outcome=outcome,
                    reason_code=error.code,
                    reason_message=error.message,
                ),
                None,
            )
        if normalized is None:
            raise RuntimeError("validated target normalization unexpectedly produced no result")
        if normalized.domain in seen:
            target_import.duplicate_count += 1
            outcome, code, message = "duplicate", "duplicate_in_import", "Domain is duplicated."
        elif normalized.domain in existing:
            target_import.already_present_count += 1
            outcome, code, message = (
                "already_present",
                "already_present",
                "Domain already exists in this campaign.",
            )
        else:
            seen.add(normalized.domain)
            target_import.accepted_count += 1
            outcome, code, message = "accepted", None, None
        row = ScanTargetImportRow(
            import_id=target_import.id,
            row_number=source.row_number,
            raw_value=source.raw_value,
            normalized_url=normalized.url,
            source_domain=normalized.domain,
            row_metadata=source.metadata,
            outcome=outcome,
            reason_code=code,
            reason_message=message,
        )
        target = (
            ScanTargetImportService._target(campaign.id, target_import.id, row)
            if commit and outcome == "accepted"
            else None
        )
        return row, target

    @staticmethod
    def _target(campaign_id: UUID, import_id: UUID, row: ScanTargetImportRow) -> ScanTarget:
        if row.normalized_url is None or row.source_domain is None:
            raise RuntimeError("accepted import row is missing normalized target fields")
        return ScanTarget(
            id=uuid4(),
            campaign_id=campaign_id,
            import_id=import_id,
            import_row_number=row.row_number,
            url=row.normalized_url,
            normalized_url=row.normalized_url,
            source_domain=row.source_domain,
            status="pending",
            import_metadata=row.row_metadata,
        )
