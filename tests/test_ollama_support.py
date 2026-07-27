"""Unit tests for the local-only Ollama administration safeguards."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

import pytest

SCRIPTS_DIRECTORY: Final = Path(__file__).resolve().parents[1] / "infrastructure" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from ollama_support import validated_base_url, validated_model_name  # noqa: E402


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434/"],
)
def test_validated_base_url_accepts_only_explicit_loopback_hosts(url: str) -> None:
    """Loopback HTTP endpoints are valid local administration targets."""
    assert validated_base_url(url) == url.rstrip("/")


@pytest.mark.parametrize(
    "url",
    [
        "http://ollama:11434",
        "http://192.0.2.1:11434",
        "file:///tmp/socket",
        "http://127.0.0.1:11434/api/tags",
        "http://user:password@127.0.0.1:11434",  # pragma: allowlist secret
    ],
)
def test_validated_base_url_rejects_non_loopback_or_ambiguous_targets(url: str) -> None:
    """Configuration cannot turn the helper into an arbitrary URL client."""
    with pytest.raises(ValueError):
        validated_base_url(url)


@pytest.mark.parametrize(
    "model",
    ["qwen3-vl:8b", "qwen3-coder:30b", "qwen3-embedding:0.6b", "team/model-name:v1"],
)
def test_validated_model_name_accepts_registry_identifiers(model: str) -> None:
    """Expected Ollama registry model identifiers remain configurable."""
    assert validated_model_name(model) == model


@pytest.mark.parametrize(
    "model", ["", "https://example.test/model", "model;command", "model name", "$(command)"]
)
def test_validated_model_name_rejects_url_and_command_syntax(model: str) -> None:
    """Model configuration cannot contain URL or command syntax."""
    with pytest.raises(ValueError):
        validated_model_name(model)
