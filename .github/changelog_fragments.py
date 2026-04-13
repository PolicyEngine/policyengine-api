"""Helpers for locating Towncrier changelog fragments."""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TowncrierConfig:
    root: Path
    directory: Path
    types: tuple[str, ...]


def load_towncrier_config(root: Path) -> TowncrierConfig:
    with (root / "pyproject.toml").open("rb") as file:
        pyproject = tomllib.load(file)

    towncrier = pyproject["tool"]["towncrier"]
    fragment_types = tuple(
        entry["directory"]
        for entry in towncrier.get("type", [])
        if entry.get("directory")
    )
    return TowncrierConfig(
        root=root,
        directory=root / towncrier["directory"],
        types=fragment_types,
    )


def iter_valid_fragments(config: TowncrierConfig) -> list[Path]:
    fragments: list[Path] = []
    for fragment_type in config.types:
        fragment_dir = config.directory / fragment_type
        if not fragment_dir.exists():
            continue
        for path in sorted(fragment_dir.rglob("*")):
            if path.is_file() and path.name != ".gitkeep":
                fragments.append(path)
    return fragments


def iter_invalid_fragments(config: TowncrierConfig) -> list[Path]:
    fragments: list[Path] = []
    allowed_roots = {
        (config.directory / fragment_type).resolve() for fragment_type in config.types
    }
    for path in sorted(config.directory.rglob("*")):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        if path.parent.resolve() not in allowed_roots:
            fragments.append(path)
    return fragments


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    config = load_towncrier_config(root)
    valid = iter_valid_fragments(config)
    invalid = iter_invalid_fragments(config)

    if invalid:
        print("Invalid changelog fragments:", file=sys.stderr)
        for path in invalid:
            print(path.relative_to(root), file=sys.stderr)
        return 1

    if not valid:
        print("No valid changelog fragments found", file=sys.stderr)
        return 1

    for path in valid:
        print(path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
