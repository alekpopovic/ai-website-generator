"""Explicitly pull configurable local Ollama models with progress output."""

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
    stream_pull,
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
        "--only",
        action="append",
        choices=("vision", "generation", "embedding"),
        help="Pull only the selected role; repeat to select multiple roles",
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Pull selected models only after an operator invokes this script."""
    args = parser().parse_args(argv)
    try:
        base_url = validated_base_url(args.url)
        configured = {
            "vision": validated_model_name(args.vision),
            "generation": validated_model_name(args.generation),
            "embedding": validated_model_name(args.embedding),
        }
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    selected = args.only or list(configured)
    for role in selected:
        model = configured[role]
        print(f"Pulling {role} model {model}. This may be a large download.")
        try:
            for update in stream_pull(base_url, model):
                status = update.get("status", "working")
                completed = update.get("completed")
                total = update.get("total")
                progress = f" ({completed}/{total} bytes)" if completed and total else ""
                print(f"  {status}{progress}")
                if pull_error := update.get("error"):
                    raise RuntimeError(str(pull_error))
        except (HTTPError, URLError, TimeoutError, ValueError, RuntimeError) as error:
            print(f"Failed to pull {model}: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
