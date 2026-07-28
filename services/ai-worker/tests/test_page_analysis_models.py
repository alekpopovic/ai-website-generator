"""Adversarial page-analysis output contract tests."""

import pytest
from platform_ai_worker.page_analysis_models import (
    DspyVisionCapability,
    PageAnalysisRequest,
    UncertaintyNote,
)
from pydantic import ValidationError


def test_uncertainty_notes_cannot_carry_arbitrary_source_copy() -> None:
    with pytest.raises(ValidationError):
        UncertaintyNote.model_validate(
            {
                "category": "structure",
                "code": "insufficient-evidence",
                "section_orders": [],
                "note": "copied source sentence",
            }
        )


def test_capability_cannot_claim_usable_without_verified_transport() -> None:
    with pytest.raises(ValidationError, match="usable capability"):
        DspyVisionCapability(
            model_installed=True,
            model_advertises_vision=True,
            dspy_image_api_available=True,
            structured_output_api_available=True,
            transport_verified=False,
            usable=True,
        )


def test_request_rejects_oversized_deterministic_input_before_compaction() -> None:
    with pytest.raises(ValidationError, match="semantic snapshot exceeds"):
        PageAnalysisRequest.model_validate(
            {
                "source": {},
                "compact_semantic_snapshot": {"unknown": "x" * (2 * 1024 * 1024)},
                "deterministic_style_summary": {},
                "structural_section_candidates": [],
                "desktop_screenshot": b"\x89PNG\r\n\x1a\n",
            }
        )
