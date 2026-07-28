"""Persistence invariants and owner-scoped curation for structured analysis."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Literal, cast
from uuid import UUID

from platform_schemas import PageProfile as PageProfileSchema
from platform_schemas import SectionPattern as SectionPatternSchema
from platform_schemas import StyleTag
from platform_schemas import WebsiteProfile as WebsiteProfileSchema

from platform_api.analysis.patterns import pattern_hash, retrieval_document
from platform_api.analysis.repository import AnalysisRepository
from platform_api.analysis.schemas import (
    AnalysisRunResponse,
    CurationRequest,
    PageAnalysisPersistenceInput,
    PageProfileResponse,
    SectionPatternResponse,
    WebsiteAnalysisPersistenceInput,
    WebsiteProfileResponse,
)
from platform_api.errors import ApiError
from platform_api.persistence.audit import AuditLogService
from platform_api.persistence.json import JsonValue, normalize_json_value
from platform_api.persistence.models import (
    AnalysisRun,
    PageProfile,
    SectionPattern,
    WebsiteProfile,
)
from platform_api.persistence.pagination import Page


class AnalysisProfileService:
    def __init__(self, repository: AnalysisRepository, audit: AuditLogService) -> None:
        self._repository = repository
        self._audit = audit

    async def persist_page(self, value: PageAnalysisPersistenceInput) -> PageProfileResponse:
        """Persist one validated result and its independent sections atomically."""
        if value.profile.source_page_id != value.source_page_id:
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "analysis_source_mismatch",
                "Profile source page does not match the persistence command.",
            )
        if value.profile.schema_version != value.run.schema_version:
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "analysis_schema_mismatch",
                "Profile and run schema versions differ.",
            )
        if await self._repository.run(value.run.id) is not None:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "analysis_run_exists",
                "This analysis run is already persisted.",
            )
        if not await self._repository.validate_page_context(
            project_id=value.project_id,
            campaign_id=value.campaign_id,
            website_id=value.source_website_id,
            page_id=value.source_page_id,
        ):
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                "analysis_source_not_found",
                "The analysis source context was not found.",
            )

        run = _run(
            value, output_kind="page", source_page_id=value.source_page_id, profile=value.profile
        )
        self._repository.add(run)
        await self._repository.clear_current_page(value.source_page_id)
        tags = tuple(tag.value for tag in value.design_tokens.style_tags)
        profile = PageProfile(
            project_id=value.project_id,
            campaign_id=value.campaign_id,
            source_website_id=value.source_website_id,
            source_page_id=value.source_page_id,
            analysis_run_id=run.id,
            profile_json=normalize_json_value(value.profile.model_dump(mode="json")),
            page_type=value.profile.page_type.value,
            category=value.profile.page_type.value,
            language=value.language,
            style_tags=list(tags),
            confidence=value.profile.confidence.overall,
            schema_version=value.profile.schema_version,
            analyzer_version=value.run.analyzer_version,
            model_digest=value.run.model_digest,
            approval_state="needs_review",
            provenance_state=value.provenance_state,
            is_current=True,
        )
        self._repository.add(profile)
        await self._repository.flush()
        for item in value.profile.sections:
            digest = pattern_hash(item, value.design_tokens.style_tags)
            duplicate = await self._repository.duplicate_pattern(
                project_id=value.project_id,
                website_id=value.source_website_id,
                page_id=value.source_page_id,
                digest=digest,
            )
            self._repository.add(
                SectionPattern(
                    project_id=value.project_id,
                    campaign_id=value.campaign_id,
                    source_website_id=value.source_website_id,
                    source_page_id=value.source_page_id,
                    analysis_run_id=run.id,
                    page_profile_id=profile.id,
                    duplicate_of_id=duplicate.id if duplicate is not None else None,
                    pattern_json=normalize_json_value(item.model_dump(mode="json")),
                    section_order=item.order,
                    section_type=item.section_type.value,
                    layout=item.layout,
                    style_tags=list(tags),
                    category=value.profile.page_type.value,
                    language=value.language,
                    confidence=value.profile.confidence.structure,
                    schema_version=item.schema_version,
                    analyzer_version=value.run.analyzer_version,
                    model_digest=value.run.model_digest,
                    approval_state="needs_review",
                    provenance_state=value.provenance_state,
                    retrieval_document=retrieval_document(
                        item,
                        category=value.profile.page_type.value,
                        language=value.language,
                        style_tags=value.design_tokens.style_tags,
                    ),
                    pattern_hash=digest,
                )
            )
            await self._repository.flush()
        return _page_response(profile)

    async def persist_website(
        self, value: WebsiteAnalysisPersistenceInput
    ) -> WebsiteProfileResponse:
        if value.profile.provenance.source_website_id != value.source_website_id:
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "analysis_source_mismatch",
                "Website profile provenance does not match the persistence command.",
            )
        if value.profile.schema_version != value.run.schema_version:
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "analysis_schema_mismatch",
                "Profile and run schema versions differ.",
            )
        if await self._repository.run(value.run.id) is not None:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "analysis_run_exists",
                "This analysis run is already persisted.",
            )
        if not await self._repository.validate_website_context(
            project_id=value.project_id,
            campaign_id=value.campaign_id,
            website_id=value.source_website_id,
        ):
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                "analysis_source_not_found",
                "The analysis source context was not found.",
            )
        run = _run(value, output_kind="website", source_page_id=None, profile=value.profile)
        self._repository.add(run)
        await self._repository.clear_current_website(value.source_website_id)
        profile = WebsiteProfile(
            project_id=value.project_id,
            campaign_id=value.campaign_id,
            source_website_id=value.source_website_id,
            analysis_run_id=run.id,
            profile_json=normalize_json_value(value.profile.model_dump(mode="json")),
            category=value.category,
            language=value.language,
            style_tags=[tag.value for tag in value.profile.design_tokens.style_tags],
            confidence=value.profile.confidence.overall,
            schema_version=value.profile.schema_version,
            analyzer_version=value.run.analyzer_version,
            model_digest=value.run.model_digest,
            approval_state="needs_review",
            provenance_state=value.provenance_state,
            is_current=True,
        )
        self._repository.add(profile)
        await self._repository.flush()
        return _website_response(profile)

    async def list_pages(
        self, project_id: UUID, owner_id: UUID, *, limit: int, offset: int, current_only: bool
    ) -> Page[PageProfileResponse]:
        page = await self._repository.list_pages(
            project_id=project_id,
            owner_id=owner_id,
            limit=limit,
            offset=offset,
            current_only=current_only,
        )
        return _map_owned_page(page, _page_response)

    async def list_websites(
        self, project_id: UUID, owner_id: UUID, *, limit: int, offset: int, current_only: bool
    ) -> Page[WebsiteProfileResponse]:
        page = await self._repository.list_websites(
            project_id=project_id,
            owner_id=owner_id,
            limit=limit,
            offset=offset,
            current_only=current_only,
        )
        return _map_owned_page(page, _website_response)

    async def list_patterns(
        self,
        project_id: UUID,
        owner_id: UUID,
        *,
        limit: int,
        offset: int,
        section_type: str | None,
        approval_state: str | None,
    ) -> Page[SectionPatternResponse]:
        page = await self._repository.list_patterns(
            project_id=project_id,
            owner_id=owner_id,
            limit=limit,
            offset=offset,
            section_type=section_type,
            approval_state=approval_state,
        )
        return _map_owned_page(page, _pattern_response)

    async def list_runs(
        self, project_id: UUID, owner_id: UUID, *, limit: int, offset: int
    ) -> Page[AnalysisRunResponse]:
        page = await self._repository.list_runs(
            project_id=project_id, owner_id=owner_id, limit=limit, offset=offset
        )
        return _map_owned_page(page, AnalysisRunResponse.model_validate)

    async def get_page(
        self, project_id: UUID, profile_id: UUID, owner_id: UUID
    ) -> PageProfileResponse:
        entity = await self._repository.owned_page(profile_id, project_id, owner_id)
        return _page_response(_found(entity))

    async def get_website(
        self, project_id: UUID, profile_id: UUID, owner_id: UUID
    ) -> WebsiteProfileResponse:
        entity = await self._repository.owned_website(profile_id, project_id, owner_id)
        return _website_response(_found(entity))

    async def get_pattern(
        self, project_id: UUID, pattern_id: UUID, owner_id: UUID
    ) -> SectionPatternResponse:
        entity = await self._repository.owned_pattern(pattern_id, project_id, owner_id)
        return _pattern_response(_found(entity))

    async def curate_page(
        self,
        project_id: UUID,
        profile_id: UUID,
        payload: CurationRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> PageProfileResponse:
        entity = _found(
            await self._repository.owned_page(profile_id, project_id, owner_id, for_update=True)
        )
        await self._curate(
            entity, payload, owner_id=owner_id, request_id=request_id, resource_type="page_profile"
        )
        return _page_response(entity)

    async def curate_website(
        self,
        project_id: UUID,
        profile_id: UUID,
        payload: CurationRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> WebsiteProfileResponse:
        entity = _found(
            await self._repository.owned_website(profile_id, project_id, owner_id, for_update=True)
        )
        await self._curate(
            entity,
            payload,
            owner_id=owner_id,
            request_id=request_id,
            resource_type="website_profile",
        )
        return _website_response(entity)

    async def curate_pattern(
        self,
        project_id: UUID,
        pattern_id: UUID,
        payload: CurationRequest,
        *,
        owner_id: UUID,
        request_id: str,
    ) -> SectionPatternResponse:
        entity = _found(
            await self._repository.owned_pattern(pattern_id, project_id, owner_id, for_update=True)
        )
        await self._curate(
            entity,
            payload,
            owner_id=owner_id,
            request_id=request_id,
            resource_type="section_pattern",
        )
        return _pattern_response(entity)

    async def _curate(
        self,
        entity: PageProfile | WebsiteProfile | SectionPattern,
        payload: CurationRequest,
        *,
        owner_id: UUID,
        request_id: str,
        resource_type: str,
    ) -> None:
        if entity.version != payload.version:
            raise ApiError(
                HTTPStatus.CONFLICT,
                "analysis_version_conflict",
                "The review item changed. Reload and try again.",
            )
        previous = entity.approval_state
        entity.approval_state = payload.approval_state
        entity.review_note = payload.note
        entity.reviewed_by_user_id = owner_id
        entity.reviewed_at = datetime.now(UTC)
        await self._repository.flush()
        self._audit.record(
            action=f"analysis.{resource_type}.{payload.approval_state}",
            resource_type=resource_type,
            resource_id=entity.id,
            actor_user_id=owner_id,
            request_id=request_id,
            details={"from_state": previous, "to_state": payload.approval_state},
        )


def _run(
    value: PageAnalysisPersistenceInput | WebsiteAnalysisPersistenceInput,
    *,
    output_kind: Literal["page", "website"],
    source_page_id: UUID | None,
    profile: PageProfileSchema | WebsiteProfileSchema,
) -> AnalysisRun:
    payload = json.dumps(profile.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return AnalysisRun(
        id=value.run.id,
        project_id=value.project_id,
        campaign_id=value.campaign_id,
        source_website_id=value.source_website_id,
        source_page_id=source_page_id,
        output_kind=output_kind,
        status="succeeded",
        prompt_version=value.run.prompt_version,
        analyzer_version=value.run.analyzer_version,
        strategy=value.run.strategy,
        model_name=value.run.model_name,
        model_digest=value.run.model_digest,
        schema_version=value.run.schema_version,
        latency_ms=value.run.latency_ms,
        attempts=value.run.attempts,
        used_fallback=value.run.used_fallback,
        provenance_state=value.provenance_state,
        result_sha256=hashlib.sha256(payload.encode()).hexdigest(),
    )


def _json_tuple(value: JsonValue) -> tuple[StyleTag, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("stored style tags are invalid")
    return tuple(StyleTag(cast(str, item)) for item in value)


def _page_response(entity: PageProfile) -> PageProfileResponse:
    return PageProfileResponse(
        **{
            key: getattr(entity, key)
            for key in PageProfileResponse.model_fields
            if key not in {"profile", "style_tags"}
        },
        profile=PageProfileSchema.model_validate(entity.profile_json),
        style_tags=_json_tuple(entity.style_tags),
    )


def _website_response(entity: WebsiteProfile) -> WebsiteProfileResponse:
    return WebsiteProfileResponse(
        **{
            key: getattr(entity, key)
            for key in WebsiteProfileResponse.model_fields
            if key not in {"profile", "style_tags"}
        },
        profile=WebsiteProfileSchema.model_validate(entity.profile_json),
        style_tags=_json_tuple(entity.style_tags),
    )


def _pattern_response(entity: SectionPattern) -> SectionPatternResponse:
    return SectionPatternResponse(
        **{
            key: getattr(entity, key)
            for key in SectionPatternResponse.model_fields
            if key not in {"pattern", "style_tags"}
        },
        pattern=SectionPatternSchema.model_validate(entity.pattern_json),
        style_tags=_json_tuple(entity.style_tags),
    )


def _found[EntityT](entity: EntityT | None) -> EntityT:
    if entity is None:
        raise ApiError(
            HTTPStatus.NOT_FOUND,
            "analysis_profile_not_found",
            "The analysis review item was not found.",
        )
    return entity


def _map_owned_page[EntityT, ResponseT](
    page: Page[EntityT] | None, mapper: Callable[[EntityT], ResponseT]
) -> Page[ResponseT]:
    if page is None:
        raise ApiError(HTTPStatus.NOT_FOUND, "project_not_found", "Project was not found.")
    items = tuple(mapper(item) for item in page.items)
    return Page(items=items, total=page.total, limit=page.limit, offset=page.offset)
