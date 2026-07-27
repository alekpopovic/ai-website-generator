"""Check local Ollama availability and the configured model inventory."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from urllib.error import HTTPError, URLError

from ollama_support import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_VISION_MODEL,
    fetch_models,
    validated_base_url,
    validated_model_name,
)


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--url", default=os.getenv("OLLAMA_URL", DEFAULT_OLLAMA_URL))
    result.add_argument("--vision", default=os.getenv("OLLAMA_VISION_MODEL", DEFAULT_VISION_MODEL))
    result.add_argument(
        "--generation", default=os.getenv("OLLAMA_GENERATION_MODEL", DEFAULT_GENERATION_MODEL)
    )
    result.add_argument(
        "--embedding", default=os.getenv("OLLAMA_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    )
    result.add_argument(
        "--server-only", action="store_true", help="Check the server without requiring models"
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Return success only when Ollama and all requested models are ready."""
    args = parser().parse_args(argv)
    try:
        base_url = validated_base_url(args.url)
        required = {
            validated_model_name(args.vision),
            validated_model_name(args.generation),
            validated_model_name(args.embedding),
        }
        installed = fetch_models(base_url)
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        print(f"Ollama readiness check failed: {error}", file=sys.stderr)
        return 1

    print(f"Ollama is available at {base_url} ({len(installed)} model names reported).")
    if args.server_only:
        return 0
    missing = sorted(required - installed)
    if missing:
        print("Missing required models:", file=sys.stderr)
        for model in missing:
            print(f"- {model}", file=sys.stderr)
        return 1
    print("All configured models are present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
