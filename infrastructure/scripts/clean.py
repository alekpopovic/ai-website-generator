"""Remove known generated development artifacts from inside this repository."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
TOP_LEVEL_TARGETS: Final = (
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "artifacts",
    "coverage",
    "dist",
    "generated",
    "htmlcov",
    "node_modules",
    "playwright-report",
    "site-output",
    "test-results",
)
NESTED_TARGET_NAMES: Final = frozenset(
    {
        ".angular",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "coverage",
        "dist",
        "node_modules",
        "out-tsc",
    }
)


def remove_directory(path: Path) -> None:
    """Remove a resolved directory only when it is strictly below the repository root."""
    resolved = path.resolve()
    if resolved == ROOT or ROOT not in resolved.parents:
        raise ValueError(f"Refusing to remove path outside repository: {resolved}")
    if resolved.is_dir():
        shutil.rmtree(resolved)
        print(f"Removed {resolved.relative_to(ROOT)}")


def main() -> None:
    """Remove explicitly allowed cache, dependency, build, and test-output directories."""
    for name in TOP_LEVEL_TARGETS:
        remove_directory(ROOT / name)

    for subtree_name in ("apps", "packages", "services", "tests"):
        subtree = ROOT / subtree_name
        if not subtree.exists():
            continue
        candidates = sorted(
            (path for path in subtree.rglob("*") if path.name in NESTED_TARGET_NAMES),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for candidate in candidates:
            remove_directory(candidate)


if __name__ == "__main__":
    main()
