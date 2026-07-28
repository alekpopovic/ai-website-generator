"""Deterministic conversion from browser style summaries into analysis tokens."""

from __future__ import annotations

import re
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from platform_schemas.analysis import (
    ColorToken,
    ColorTokens,
    DesignTokens,
    FontCategory,
    SpacingTokens,
    TypographyTokens,
)

_PIXEL_VALUE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)px$")
_WEIGHT_VALUE = re.compile(r"^[1-9][0-9]{0,3}$")
_TRANSPARENT = {"transparent", "rgba(0, 0, 0, 0)", "rgba(0,0,0,0)"}


class _Frequency(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str = Field(min_length=1, max_length=240)
    count: int = Field(ge=1, le=100_000)


class _StyleSummary(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    colors: tuple[_Frequency, ...] = Field(default=(), max_length=100)
    font_families: tuple[_Frequency, ...] = Field(default=(), max_length=100)
    font_sizes: tuple[_Frequency, ...] = Field(default=(), max_length=100)
    font_weights: tuple[_Frequency, ...] = Field(default=(), max_length=100)
    line_heights: tuple[_Frequency, ...] = Field(default=(), max_length=100)
    spacing: tuple[_Frequency, ...] = Field(default=(), max_length=100)
    radii: tuple[_Frequency, ...] = Field(default=(), max_length=100)


def design_tokens_from_style_summary(style_summary: Mapping[str, object]) -> DesignTokens:
    """Convert hostile-but-validated frequency data without inference or source copy."""

    summary = _StyleSummary.model_validate(style_summary)
    colors: list[ColorToken] = []
    for entry in _ordered(summary.colors):
        if entry.value.casefold() in _TRANSPARENT:
            continue
        try:
            token = ColorToken(
                name=f"color-{len(colors) + 1}", value=entry.value, frequency=entry.count
            )
        except ValueError:
            continue
        colors.append(token)
        if len(colors) == 24:
            break
    families = tuple(
        dict.fromkeys(_font_category(entry.value) for entry in _ordered(summary.font_families))
    )[:8]
    return DesignTokens(
        colors=ColorTokens(palette=tuple(colors)),
        typography=TypographyTokens(
            font_families=families,
            font_sizes_px=_numeric_scale(summary.font_sizes, maximum=512, limit=20),
            font_weights=_integer_scale(summary.font_weights, maximum=1000, limit=12),
            line_heights_px=_numeric_scale(summary.line_heights, maximum=512, limit=20),
        ),
        spacing=SpacingTokens(
            scale_px=_numeric_scale(summary.spacing, maximum=2048, limit=24, allow_zero=True),
            radius_px=_numeric_scale(summary.radii, maximum=1024, limit=16, allow_zero=True),
        ),
    )


def _ordered(values: tuple[_Frequency, ...]) -> tuple[_Frequency, ...]:
    return tuple(sorted(values, key=lambda item: (-item.count, item.value.casefold())))


def _numeric_scale(
    values: tuple[_Frequency, ...],
    *,
    maximum: float,
    limit: int,
    allow_zero: bool = False,
) -> tuple[float, ...]:
    parsed: set[float] = set()
    for entry in values:
        match = _PIXEL_VALUE.fullmatch(entry.value.strip())
        if match is None:
            continue
        value = round(float(match.group(1)), 4)
        if (value > 0 or allow_zero) and value <= maximum:
            parsed.add(value)
    return tuple(sorted(parsed))[:limit]


def _integer_scale(values: tuple[_Frequency, ...], *, maximum: int, limit: int) -> tuple[int, ...]:
    parsed = {
        int(entry.value)
        for entry in values
        if _WEIGHT_VALUE.fullmatch(entry.value.strip()) and 1 <= int(entry.value) <= maximum
    }
    return tuple(sorted(parsed))[:limit]


def _font_category(value: str) -> FontCategory:
    normalized = value.casefold()
    if any(token in normalized for token in ("system-ui", "ui-sans-serif", "-apple-system")):
        return FontCategory.SYSTEM_SANS
    if "monospace" in normalized:
        return FontCategory.MONOSPACE
    if "sans-serif" in normalized:
        return FontCategory.SANS_SERIF
    if "serif" in normalized:
        return FontCategory.SERIF
    if "cursive" in normalized:
        return FontCategory.CURSIVE
    if "fantasy" in normalized:
        return FontCategory.DISPLAY
    return FontCategory.UNKNOWN
