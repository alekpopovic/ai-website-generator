"""Typed write-boundary and owner review contracts for normalized analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from platform_schemas import (
    DesignTokens,
    PageProfile,
    PageType,
    SectionPattern,
    SectionType,
    StyleTag,
    WebsiteProfile,
)
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ApprovalState = Literal["needs_review", "approved", "rejected"]
ProvenanceState = Literal["authorized", "restricted", "removal_pending", "removed"]
Language = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=2,
        max_length=35,
        pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$",
    ),
]


class AnalysisWriteModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AnalysisRunInput(AnalysisWriteModel):
    id: UUID
    prompt_version: str = Field(min_length=1, max_length=100)
    analyzer_version: str = Field(min_length=1, max_length=100)
    strategy: Literal["dspy", "direct-structured-fallback", "deterministic"]
    model_name: str = Field(min_length=1, max_length=200)
    model_digest: str = Field(min_length=1, max_length=200)
    schema_version: int = Field(ge=1)
    latency_ms: int = Field(ge=0)
    attempts: int = Field(ge=1, le=10)
    used_fallback: bool = False


class PageAnalysisPersistenceInput(AnalysisWriteModel):
    project_id: UUID
    campaign_id: UUID
    source_website_id: UUID
    source_page_id: UUID
    run: AnalysisRunInput
    profile: PageProfile
    design_tokens: DesignTokens
    language: Language
    provenance_state: ProvenanceState = "authorized"


class WebsiteAnalysisPersistenceInput(AnalysisWriteModel):
    project_id: UUID
    campaign_id: UUID
    source_website_id: UUID
    run: AnalysisRunInput
    profile: WebsiteProfile
    language: Language
    category: str = Field(default="website", pattern=r"^[a-z][a-z0-9-]{0,63}$")
    provenance_state: ProvenanceState = "authorized"


class CurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    approval_state: ApprovalState
    version: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=500)


class AnalysisRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    campaign_id: UUID
    source_website_id: UUID
    source_page_id: UUID | None
    output_kind: str
    status: str
    prompt_version: str
    analyzer_version: str
    strategy: str
    model_name: str
    model_digest: str
    schema_version: int
    latency_ms: int
    attempts: int
    used_fallback: bool
    provenance_state: str
    created_at: datetime


class PageProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    campaign_id: UUID
    source_website_id: UUID
    source_page_id: UUID
    analysis_run_id: UUID
    profile: PageProfile
    page_type: PageType
    category: PageType
    language: str
    style_tags: tuple[StyleTag, ...]
    confidence: float
    schema_version: int
    analyzer_version: str
    model_digest: str
    approval_state: ApprovalState
    provenance_state: ProvenanceState
    is_current: bool
    review_note: str | None
    reviewed_at: datetime | None
    created_at: datetime
    version: int


class WebsiteProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    campaign_id: UUID
    source_website_id: UUID
    analysis_run_id: UUID
    profile: WebsiteProfile
    category: str
    language: str
    style_tags: tuple[StyleTag, ...]
    confidence: float
    schema_version: int
    analyzer_version: str
    model_digest: str
    approval_state: ApprovalState
    provenance_state: ProvenanceState
    is_current: bool
    review_note: str | None
    reviewed_at: datetime | None
    created_at: datetime
    version: int


class SectionPatternResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    campaign_id: UUID
    source_website_id: UUID
    source_page_id: UUID
    analysis_run_id: UUID
    page_profile_id: UUID
    duplicate_of_id: UUID | None
    pattern: SectionPattern
    section_order: int
    section_type: SectionType
    layout: Literal[
        "single-column",
        "two-column",
        "three-column",
        "multi-column",
        "grid",
        "split",
        "overlay",
        "unknown",
    ]
    style_tags: tuple[StyleTag, ...]
    category: PageType
    language: str
    confidence: float
    schema_version: int
    analyzer_version: str
    model_digest: str
    approval_state: ApprovalState
    provenance_state: ProvenanceState
    retrieval_document: str
    pattern_hash: str
    review_note: str | None
    reviewed_at: datetime | None
    created_at: datetime
    version: int
