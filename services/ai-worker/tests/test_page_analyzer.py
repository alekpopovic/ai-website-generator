"""Deterministic page analysis, compaction, fallback, and capability tests."""

from __future__ import annotations

from uuid import UUID

import pytest
from platform_ai_worker.dspy_program import (
    DspyOllamaVisionProgram,
    DspyProgramResult,
    DspyVisionCompatibilityError,
)
from platform_ai_worker.input_compaction import CompactedAnalysisInput, compact_analysis_input
from platform_ai_worker.page_analysis_models import (
    AnalyzerStrategy,
    PageAnalysisPayload,
    PageAnalysisRequest,
    PageAnalysisSource,
    ViewportMetadata,
)
from platform_ai_worker.page_analyzer import (
    DspyPageAnalyzer,
    PageAnalysisOutputMismatchError,
    _direct_prompt,
)
from platform_clients.llm.fake import FakeLLMGateway
from platform_clients.llm.models import ModelRole
from platform_schemas import (
    AnalysisConfidence,
    ColorTokens,
    CopyPurpose,
    DesignTokens,
    PageProfile,
    PageType,
    SectionPattern,
    SectionType,
    SpacingTokens,
    TypographyTokens,
)

SOURCE_PAGE_ID = UUID("00000000-0000-4000-8000-000000000004")
PNG = b"\x89PNG\r\n\x1a\nfixture"


class FakeDspyProgram:
    def __init__(self, payload: PageAnalysisPayload, *, transport: bool = True) -> None:
        self.payload = payload
        self.transport = transport
        self.probes = 0
        self.calls = 0
        self.last_compacted: object | None = None

    def api_capabilities(self) -> tuple[bool, bool]:
        return True, True

    async def verify_transport(self) -> bool:
        self.probes += 1
        return self.transport

    async def analyze(
        self, compacted: object, desktop_screenshot: bytes, mobile_screenshot: bytes | None
    ) -> DspyProgramResult:
        self.calls += 1
        self.last_compacted = compacted
        assert desktop_screenshot == PNG
        assert mobile_screenshot is None
        return DspyProgramResult(payload=self.payload, latency_ms=12.5, attempts=2)


class IncompatibleDspyProgram(FakeDspyProgram):
    async def analyze(
        self, compacted: object, desktop_screenshot: bytes, mobile_screenshot: bytes | None
    ) -> DspyProgramResult:
        raise DspyVisionCompatibilityError("fixture incompatibility")


class RetryingDspyProgram(DspyOllamaVisionProgram):
    def __init__(self, payload: PageAnalysisPayload) -> None:
        self._max_attempts = 2
        self.payload = payload
        self.calls = 0

    def _predict_once(
        self,
        compacted: CompactedAnalysisInput,
        desktop_screenshot: bytes,
        mobile_screenshot: bytes | None,
    ) -> PageAnalysisPayload:
        self.calls += 1
        if self.calls == 1:
            return PageAnalysisPayload.model_validate({})
        return self.payload


def _payload(*, source_page_id: UUID = SOURCE_PAGE_ID) -> PageAnalysisPayload:
    confidence = AnalysisConfidence(
        overall=0.7,
        structure=0.8,
        design_tokens=0.7,
        responsive_behavior=0.6,
        accessibility=0.6,
    )
    design_tokens = DesignTokens(
        colors=ColorTokens(), typography=TypographyTokens(), spacing=SpacingTokens()
    )
    return PageAnalysisPayload(
        page_profile=PageProfile(
            source_page_id=source_page_id,
            page_type=PageType.HOMEPAGE,
            sections=(
                SectionPattern(
                    section_type=SectionType.HERO,
                    order=0,
                    copy_purpose=CopyPurpose.VALUE_PROPOSITION,
                    layout="single-column",
                ),
            ),
            confidence=confidence,
        ),
        design_tokens=design_tokens,
    )


def _request() -> PageAnalysisRequest:
    return PageAnalysisRequest(
        source=PageAnalysisSource(
            project_id=UUID("00000000-0000-4000-8000-000000000001"),
            campaign_id=UUID("00000000-0000-4000-8000-000000000002"),
            source_website_id=UUID("00000000-0000-4000-8000-000000000003"),
            source_page_id=SOURCE_PAGE_ID,
            desktop_page_scan_id=UUID("00000000-0000-4000-8000-000000000005"),
            page_type=PageType.HOMEPAGE,
            language="en",
            scanner_version="playwright/1",
            extractor_version="semantic-v1",
            desktop_viewport=ViewportMetadata(width=1440, height=1000, document_height=2200),
        ),
        compact_semantic_snapshot={
            "nodes": [
                {
                    "id": "n-12345678",
                    "tag": "h1",
                    "role": "heading",
                    "text": "Acme's proprietary original sentence",
                    "aria_label": "Acme logo",
                    "font_family": "Acme Corporate Sans",
                    "bounds": {"x": 20, "y": 30, "width": 500, "height": 80},
                    "visible": True,
                    "display": "block",
                    "position": "static",
                    "layout": {"flex_direction": "row"},
                }
            ],
            "summary": {
                "node_count": 1,
                "section_count": 1,
                "card_count": 0,
                "tag_counts": {"h1": 1},
                "role_counts": {"heading": 1},
                "layout_counts": {"block": 1},
                "heading_outline": [{"level": "h1", "text": "Acme original sentence"}],
            },
        },
        deterministic_style_summary={
            "style_frequencies": {
                "font_families": [{"value": "Acme Corporate Sans, sans-serif", "count": 5}],
                "font_sizes": [{"value": "48px", "count": 2}],
                "colors": [{"value": "#112233", "count": 4}],
            }
        },
        structural_section_candidates=(
            {
                "id": "section-1",
                "tag": "section",
                "kind": "hero",
                "bounds": {"x": 0, "y": 0, "width": 1440, "height": 600},
                "node_count": 4,
                "text": "Acme source copy",
            },
        ),
        desktop_screenshot=PNG,
    )


def test_compaction_removes_copy_brand_and_font_names() -> None:
    compacted = compact_analysis_input(_request())
    combined = " ".join(
        (
            compacted.source_metadata,
            compacted.semantic_snapshot,
            compacted.design_token_baseline,
            compacted.structural_section_candidates,
        )
    )

    assert "Acme" not in combined
    assert "original sentence" not in combined
    assert '"font_families":["sans-serif"]' in compacted.design_token_baseline
    assert compacted.report.prompt_bytes < 196_608


def test_direct_fallback_prompt_contains_explicit_non_copying_policy() -> None:
    prompt = " ".join(_direct_prompt(compact_analysis_input(_request())).split())

    for prohibited_source in (
        "brand names",
        "original sentences",
        "logos",
        "image assets",
        "proprietary source code",
        "a complete composition",
    ):
        assert prohibited_source in prompt


def test_dspy_program_retries_invalid_structured_output_only_within_bound() -> None:
    request = _request()
    program = RetryingDspyProgram(_payload())

    result = program._analyze_sync(
        compact_analysis_input(request), request.desktop_screenshot, request.mobile_screenshot
    )

    assert result.payload == _payload()
    assert result.attempts == 2
    assert program.calls == 2


@pytest.mark.anyio
async def test_analyzer_uses_verified_dspy_and_records_safe_metadata() -> None:
    program = FakeDspyProgram(_payload())
    gateway = FakeLLMGateway()
    analyzer = DspyPageAnalyzer(gateway, program)

    result = await analyzer.analyze(_request())

    assert result.metadata.strategy is AnalyzerStrategy.DSPY
    assert result.metadata.model_name == "qwen3-vl:8b"
    assert result.metadata.model_digest == "2" * 64
    assert result.metadata.attempts == 2
    assert result.metadata.prompt_version == "page-analysis-v1"
    assert program.probes == 1
    assert program.calls == 1
    assert gateway.calls == []


@pytest.mark.anyio
async def test_failed_dspy_vision_probe_uses_direct_structured_ollama_fallback() -> None:
    payload = _payload()
    program = FakeDspyProgram(payload, transport=False)
    gateway = FakeLLMGateway(structured_payloads={"PageAnalysisPayload": payload.model_dump()})
    analyzer = DspyPageAnalyzer(gateway, program)

    result = await analyzer.analyze(_request())

    assert result.metadata.strategy is AnalyzerStrategy.DIRECT_OLLAMA
    assert result.metadata.fallback_reason == "dspy-litellm-ollama-vision-probe-failed"
    assert gateway.calls == [("vision", ModelRole.VISION)]
    assert program.probes == 1
    assert program.calls == 0


@pytest.mark.anyio
async def test_capability_is_not_claimed_without_transport_probe() -> None:
    analyzer = DspyPageAnalyzer(
        FakeLLMGateway(), FakeDspyProgram(_payload()), verify_dspy_transport=False
    )

    capability = await analyzer.capabilities()

    assert capability.usable is False
    assert capability.transport_verified is False
    assert capability.reason == "dspy-vision-transport-not-verified"


@pytest.mark.anyio
async def test_runtime_structured_vision_incompatibility_uses_direct_fallback() -> None:
    payload = _payload()
    gateway = FakeLLMGateway(structured_payloads={"PageAnalysisPayload": payload.model_dump()})
    analyzer = DspyPageAnalyzer(gateway, IncompatibleDspyProgram(payload))

    result = await analyzer.analyze(_request())

    assert result.metadata.strategy is AnalyzerStrategy.DIRECT_OLLAMA
    assert result.metadata.fallback_reason == "dspy-litellm-runtime-structured-vision-incompatible"
    assert gateway.calls == [("vision", ModelRole.VISION)]


@pytest.mark.anyio
async def test_analyzer_rejects_model_output_that_changes_source_identity() -> None:
    program = FakeDspyProgram(_payload(source_page_id=UUID("00000000-0000-4000-8000-000000000099")))
    analyzer = DspyPageAnalyzer(FakeLLMGateway(), program)

    with pytest.raises(PageAnalysisOutputMismatchError, match="source page identifier"):
        await analyzer.analyze(_request())
