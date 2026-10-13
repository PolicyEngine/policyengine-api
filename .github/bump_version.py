"""Infer semver bump from towncrier fragment types and update version."""

import re
import sys
from pathlib import Path
from typing import TextIO


def _report(message: str, *, file: TextIO | None = None) -> None:
    """Print one line of this command's output, to stdout unless ``file`` is given."""
    print(message, file=file)


def get_current_version(pyproject_path: Path) -> str:
    """Return the version in pyproject.toml, exiting with status 1 if it is absent."""
    text = pyproject_path.read_text()
    match = re.search(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', text, re.MULTILINE)
    if not match:
        _report(
            "Could not find version in pyproject.toml",
            file=sys.stderr,
        )
        sys.exit(1)
    return match.group(1)


def infer_bump(changelog_dir: Path) -> str:
    """Return "major", "minor" or "patch" from the pending changelog fragment types.

    Any breaking fragment makes a major bump and any added or removed fragment a
    minor one; exit with status 1 when there are no fragments.
    """
    fragments = [
        f for f in changelog_dir.iterdir() if f.is_file() and f.name != ".gitkeep"
    ]
    if not fragments:
        _report("No changelog fragments found", file=sys.stderr)
        sys.exit(1)

    categories = {f.suffix.lstrip(".") for f in fragments}
    for f in fragments:
        parts = f.stem.split(".")
        if len(parts) >= 2:
            categories.add(parts[-1])

    if "breaking" in categories:
        return "major"
    if "added" in categories or "removed" in categories:
        return "minor"
    return "patch"


def bump_version(version: str, bump: str) -> str:
    """Return ``version`` raised by one ``bump`` level, resetting the lower parts."""
    major, minor, patch = (int(x) for x in version.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def update_file(path: Path, old_version: str, new_version: str) -> None:
    """Rewrite the ``version = "..."`` line in ``path``; leave other files untouched."""
    text = path.read_text()
    updated = text.replace(
        f'version = "{old_version}"',
        f'version = "{new_version}"',
    )
    if updated != text:
        path.write_text(updated)
        _report(f"  Updated {path}")


def main() -> None:
    """Bump the version in pyproject.toml according to the changelog.d fragments."""
    root = Path(__file__).resolve().parent.parent
    pyproject = root / "pyproject.toml"
    changelog_dir = root / "changelog.d"

    current = get_current_version(pyproject)
    bump = infer_bump(changelog_dir)
    new = bump_version(current, bump)

    _report(f"Version: {current} -> {new} ({bump})")

    update_file(pyproject, current, new)


if __name__ == "__main__":
    main()
