"""Run a test category while allowing an unimplemented monorepo to contain no tests."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Final, Literal, cast

TestKind = Literal["unit", "integration", "e2e"]

ROOT: Final = Path(__file__).resolve().parents[2]
SEARCH_ROOTS: Final = (
    ROOT / "apps",
    ROOT / "packages" / "python",
    ROOT / "services",
    ROOT / "tests",
)


def parse_args() -> argparse.Namespace:
    """Parse the requested test category."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("unit", "integration", "e2e"))
    return parser.parse_args()


def test_files(kind: TestKind) -> list[Path]:
    """Return Python test files belonging to the requested category."""
    files: list[Path] = []
    for search_root in SEARCH_ROOTS:
        if not search_root.exists():
            continue
        for candidate in search_root.rglob("test_*.py"):
            relative_parts = candidate.relative_to(ROOT).parts
            is_integration = "integration" in relative_parts
            is_e2e = "e2e" in relative_parts
            matches_kind = (
                (kind == "unit" and not is_integration and not is_e2e)
                or (kind == "integration" and is_integration)
                or (kind == "e2e" and is_e2e)
            )
            if matches_kind:
                files.append(candidate)
    return sorted(files)


def main() -> int:
    """Run pytest for the selected category, or succeed if none exist yet."""
    kind = cast(TestKind, parse_args().kind)
    files = test_files(kind)
    if not files:
        print(f"No Python {kind} tests are implemented yet; nothing to run.")
        return 0

    command = [sys.executable, "-m", "pytest", *(str(path) for path in files)]
    return subprocess.run(command, check=False, cwd=ROOT).returncode  # noqa: S603


if __name__ == "__main__":
    raise SystemExit(main())
