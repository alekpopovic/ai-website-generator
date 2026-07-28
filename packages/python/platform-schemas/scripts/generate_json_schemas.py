"""Generate or verify deterministic JSON Schema artifacts for analysis contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from platform_schemas.analysis import (
    AccessibilityObservation,
    AnalysisConfidence,
    AnalysisProvenance,
    ColorTokens,
    ComponentPattern,
    DesignTokens,
    PageProfile,
    ResponsiveBehavior,
    SectionPattern,
    SpacingTokens,
    TypographyTokens,
    WebsiteProfile,
)
from pydantic import BaseModel

SCHEMAS: tuple[type[BaseModel], ...] = (
    WebsiteProfile,
    PageProfile,
    DesignTokens,
    TypographyTokens,
    ColorTokens,
    SpacingTokens,
    SectionPattern,
    ComponentPattern,
    ResponsiveBehavior,
    AccessibilityObservation,
    AnalysisConfidence,
    AnalysisProvenance,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output_directory = Path(__file__).resolve().parents[1] / "json-schema"
    expected = {f"{_kebab_case(model.__name__)}-v1.json": _render(model) for model in SCHEMAS}
    if args.check:
        missing_or_stale = [
            name
            for name, content in expected.items()
            if not (output_directory / name).is_file()
            or (output_directory / name).read_text(encoding="utf-8") != content
        ]
        unexpected = (
            {path.name for path in output_directory.glob("*.json")} - set(expected)
            if output_directory.exists()
            else set()
        )
        if missing_or_stale or unexpected:
            names = sorted([*missing_or_stale, *unexpected])
            raise SystemExit(f"analysis JSON Schema artifacts are stale: {', '.join(names)}")
        return
    output_directory.mkdir(parents=True, exist_ok=True)
    for name, content in expected.items():
        (output_directory / name).write_text(content, encoding="utf-8", newline="\n")


def _render(model: type[BaseModel]) -> str:
    schema = model.model_json_schema(ref_template="#/$defs/{model}")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = (
        f"https://schemas.ai-website-generator.local/analysis/v1/{_kebab_case(model.__name__)}.json"
    )
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _kebab_case(value: str) -> str:
    characters: list[str] = []
    for index, character in enumerate(value):
        if character.isupper() and index:
            characters.append("-")
        characters.append(character.casefold())
    return "".join(characters)


if __name__ == "__main__":
    main()
