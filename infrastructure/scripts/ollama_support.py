"""Shared, loopback-only helpers for local Ollama administration scripts."""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Iterator
from http.client import HTTPResponse
from typing import Final, TypedDict, cast
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_OLLAMA_URL: Final = "http://127.0.0.1:11434"
DEFAULT_VISION_MODEL: Final = "qwen3-vl:8b"
DEFAULT_GENERATION_MODEL: Final = "qwen3-coder:30b"
DEFAULT_EMBEDDING_MODEL: Final = "qwen3-embedding:0.6b"
MODEL_NAME_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9._-]+)?$")
MAX_RESPONSE_BYTES: Final = 8 * 1024 * 1024


class OllamaModel(TypedDict, total=False):
    """Fields used from an Ollama model-list entry."""

    name: str
    model: str


class OllamaTagsResponse(TypedDict):
    """Relevant shape returned by Ollama's tags endpoint."""

    models: list[OllamaModel]


def validated_base_url(raw_url: str) -> str:
    """Return a normalized HTTP loopback URL or reject unsafe destinations."""
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise ValueError("OLLAMA_URL must be an HTTP(S) URL without embedded credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("OLLAMA_URL must not include a path, query, or fragment")
    if parsed.hostname is None:
        raise ValueError("OLLAMA_URL must contain a host")
    try:
        is_loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        is_loopback = parsed.hostname.lower() == "localhost"
    if not is_loopback:
        raise ValueError("OLLAMA_URL must use localhost or a loopback IP address")
    return raw_url.rstrip("/")


def validated_model_name(model: str) -> str:
    """Reject empty model names and values that resemble URLs or command syntax."""
    if not MODEL_NAME_PATTERN.fullmatch(model):
        raise ValueError(f"Invalid Ollama model name: {model!r}")
    return model


def open_json(request: Request, *, timeout: float) -> HTTPResponse:
    """Open a local Ollama request with one bounded timeout."""
    return cast(HTTPResponse, urlopen(request, timeout=timeout))  # noqa: S310


def fetch_models(base_url: str, *, timeout: float = 10.0) -> set[str]:
    """Fetch locally installed model names from Ollama."""
    request = Request(  # noqa: S310 -- base_url is constrained to explicit loopback hosts.
        f"{base_url}/api/tags", headers={"Accept": "application/json"}
    )
    with open_json(request, timeout=timeout) as response:
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError("Ollama model-list response exceeded the safety limit")
    decoded = cast(OllamaTagsResponse, json.loads(payload))
    names: set[str] = set()
    for model in decoded.get("models", []):
        if name := model.get("name"):
            names.add(name)
        if canonical_name := model.get("model"):
            names.add(canonical_name)
    return names


def stream_pull(
    base_url: str, model: str, *, timeout: float = 3600.0
) -> Iterator[dict[str, object]]:
    """Yield bounded JSON progress records from an explicit Ollama pull request."""
    body = json.dumps({"model": model, "stream": True}).encode()
    request = Request(  # noqa: S310 -- base_url is constrained to explicit loopback hosts.
        f"{base_url}/api/pull",
        data=body,
        headers={"Accept": "application/x-ndjson", "Content-Type": "application/json"},
        method="POST",
    )
    with open_json(request, timeout=timeout) as response:
        for raw_line in response:
            if len(raw_line) > 1024 * 1024:
                raise ValueError("Ollama progress record exceeded the safety limit")
            if raw_line.strip():
                yield cast(dict[str, object], json.loads(raw_line))
