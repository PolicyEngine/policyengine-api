"""Raise the version in pyproject.toml from the pending changelog fragments' types.

The versioning job in .github/workflows/push.yml and ``make changelog`` run
this before Towncrier builds CHANGELOG.md. It reads the fragments through
``FragmentDefinition`` in changelog_fragments.py, beside this file, the
definition the PR check uses too (rule api.process.changelog-fragment). It
exits with status 1, changing nothing, when changelog.d/ holds anything that
isn't a fragment, holds no fragment, or when ``BUMP_BY_TYPE`` and the types in
[tool.towncrier] differ.
"""

import re
import sys
from pathlib import Path
from typing import NoReturn, TextIO

from changelog_fragments import (
    CONFIG_TABLE,
    ConfigurationError,
    FragmentDefinition,
)

# The version part each fragment type raises: breaking the major version, added
# and removed the minor version, and changed and fixed the patch version. Its
# keys must be the types in [tool.towncrier]; infer_bump refuses to run when
# they differ.
BUMP_BY_TYPE = {
    "breaking": "major",
    "added": "minor",
    "changed": "patch",
    "fixed": "patch",
    "removed": "minor",
}
# Version parts from the smallest bump to the largest.
BUMP_SIZES = ("patch", "minor", "major")


def _listed(names: list[str]) -> str:
    """Return ``names`` as "a, b and c", or "none"."""
    if not names:
        return "none"
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _report(message: str, *, file: TextIO | None = None) -> None:
    """Print one line of this command's output, to stdout unless ``file`` is given."""
    print(message, file=file)


def _fail(message: str) -> NoReturn:
    """Print ``message`` to stderr and exit with status 1."""
    _report(message, file=sys.stderr)
    sys.exit(1)


def get_current_version(pyproject_path: Path) -> str:
    """Return the version in pyproject.toml, exiting with status 1 if it is absent."""
    text = pyproject_path.read_text()
    match = re.search(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', text, re.MULTILINE)
    if not match:
        _fail("Could not find version in pyproject.toml")
    return match.group(1)


def _require_a_bump_for_each_type(types: tuple[str, ...]) -> None:
    """Exit with status 1 unless ``BUMP_BY_TYPE`` has a bump for exactly ``types``."""
    if set(types) == set(BUMP_BY_TYPE):
        return
    _fail(
        f"The fragment types in {CONFIG_TABLE} are {_listed(list(types))}, but "
        f"BUMP_BY_TYPE in .github/bump_version.py has a bump for "
        f"{_listed(list(BUMP_BY_TYPE))}. Types with no bump: "
        f"{_listed([name for name in types if name not in BUMP_BY_TYPE])}. "
        f"Bumps with no type: "
        f"{_listed([name for name in BUMP_BY_TYPE if name not in types])}. "
        "Change both together."
    )


def infer_bump(root: Path) -> str:
    """Return "major", "minor" or "patch" from the fragments in ``root``'s changelog.d/.

    Any breaking fragment makes a major bump and any added or removed fragment a
    minor one. Exit with status 1 when the directory holds a file that isn't a
    fragment, or no fragment.
    """
    try:
        definition = FragmentDefinition.load(root)
    except ConfigurationError as error:
        _fail(str(error))
    _require_a_bump_for_each_type(definition.types)
    scan = definition.scan(root)
    problems = [
        *scan.problems.values(),
        *(definition.empty_folder_problem(path) for path in scan.empty_folders),
    ]
    if problems:
        for problem in problems:
            _report(problem, file=sys.stderr)
        if len(problems) == 1:
            unreadable = "1 of them is not a fragment. Fix it"
        else:
            unreadable = f"{len(problems)} of them are not fragments. Fix them"
        _fail(
            f"The release reads every file in {definition.directory}/, and "
            f"{unreadable} in a pull request; the release stops until then."
        )
    if not scan.fragments:
        _fail(
            f"No changelog fragments found in {definition.directory}/: there is "
            "nothing to release."
        )
    return max(
        (BUMP_BY_TYPE[fragment.fragment_type] for fragment in scan.fragments),
        key=BUMP_SIZES.index,
    )


def bump_version(version: str, bump: str) -> str:
    """Return ``version`` raised by one ``bump`` level, resetting the lower parts."""
    major, minor, patch = (int(part) for part in version.split("."))
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

    current = get_current_version(pyproject)
    bump = infer_bump(root)
    new = bump_version(current, bump)

    _report(f"Version: {current} -> {new} ({bump})")

    update_file(pyproject, current, new)


if __name__ == "__main__":
    main()
