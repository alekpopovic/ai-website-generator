"""Export the FastAPI OpenAPI document without running an HTTP server."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from platform_api.testing import create_test_app


def render_openapi() -> str:
    """Return canonical UTF-8 JSON for the deterministic test application schema."""
    schema = create_test_app().openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    """Write or verify the configured schema artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render_openapi()

    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != expected:
            parser.error(f"{args.output} is stale; run task generate-api-client")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(expected, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
