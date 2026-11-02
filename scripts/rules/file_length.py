"""The file-length quality guard: no Python file grows past a fixed size.

A tracked Python file may have at most 800 physical lines, or 1,500 if it is
test code: a file under a ``tests`` or ``fixtures`` directory, or a
``conftest.py``. Files matching one of the rule's ``[[rule.exception]]`` paths
in rules/registry.toml (applied Alembic revisions) are not measured.

While the rule is ratcheted, its baseline file lists the files tolerated over
their limit. An oversized file the baseline doesn't list fails, and so does a
listed file that is now within its limit, so the baseline only shrinks.

The rule: docs/engineering/skills/file-length.md. Standard library only.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from scripts.rules.load import load_registry
from scripts.rules.model import Violation

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
RULE_ID = "api.quality.file-length"
CHECK_NAME = "file-length"
SOURCE_LINE_LIMIT = 800
TEST_LINE_LIMIT = 1500
TEST_DIRECTORIES = frozenset({"tests", "fixtures"})
TEST_FILE_NAMES = frozenset({"conftest.py"})
SPLIT_FIX = (
    "split it by responsibility into modules under the limit, keeping its "
    "public import path (docs/engineering/skills/file-length.md)"
)


@dataclass(frozen=True)
class OversizedFile:
    """A Python file with more physical lines than its limit allows."""

    path: str
    line_count: int
    line_limit: int


def tracked_python_files(root: Path) -> list[str]:
    """Return the tracked ``.py`` files under ``root``, or every one in a plain tree.

    A directory that isn't a git checkout (a proof test's temporary tree) has
    every ``.py`` file under it measured.
    """
    if (root / ".git").exists():
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.py"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split("\0")
        return sorted(path for path in listed if path and (root / path).is_file())
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*.py"))


def is_test_code(path: str) -> bool:
    """Whether ``path`` is under a tests or fixtures directory, or is a conftest.py."""
    parts = PurePosixPath(path).parts
    return (
        any(directory in TEST_DIRECTORIES for directory in parts[:-1])
        or parts[-1] in TEST_FILE_NAMES
    )


def line_limit(path: str) -> int:
    """Return the most physical lines the file at ``path`` may have."""
    return TEST_LINE_LIMIT if is_test_code(path) else SOURCE_LINE_LIMIT


def physical_line_count(file: Path) -> int:
    """Count a file's physical lines, ending in a newline, carriage return or both.

    A final line without a line ending still counts.
    """
    with file.open(encoding="utf-8", errors="replace", newline=None) as handle:
        text = handle.read()
    unterminated_last_line = 1 if text and not text.endswith("\n") else 0
    return text.count("\n") + unterminated_last_line


def is_excluded(path: str, excluded_patterns: Iterable[str]) -> bool:
    """Whether ``path`` matches one of the glob patterns, compared part by part."""
    candidate = PurePosixPath(path)
    return any(
        candidate.match(pattern)
        and len(candidate.parts) == len(PurePosixPath(pattern).parts)
        for pattern in excluded_patterns
    )


def oversized_files(
    root: Path, excluded_patterns: Iterable[str] = ()
) -> list[OversizedFile]:
    """Return every measured Python file under ``root`` that is over its limit."""
    excluded_patterns = tuple(excluded_patterns)
    found = []
    for path in tracked_python_files(root):
        if is_excluded(path, excluded_patterns):
            continue
        count = physical_line_count(root / path)
        limit = line_limit(path)
        if count > limit:
            found.append(OversizedFile(path, count, limit))
    return found


def baseline_paths(root: Path, baseline_file: str | None) -> set[str]:
    """Read the baseline's paths, skipping blank and ``#`` comment lines."""
    if baseline_file is None or not (root / baseline_file).is_file():
        return set()
    return {
        entry.strip()
        for entry in (root / baseline_file).read_text().splitlines()
        if entry.strip() and not entry.lstrip().startswith("#")
    }


def _code_kind(path: str) -> str:
    return "test code" if is_test_code(path) else "source files"


def _stale_baseline_message(root: Path, path: str) -> str:
    file = root / path
    if not file.is_file():
        return f"baseline entry no longer applies: {path} does not exist"
    return (
        f"baseline entry no longer applies: {path} has "
        f"{physical_line_count(file)} lines, within the {line_limit(path)}-line "
        f"limit for {_code_kind(path)}"
    )


def compare(
    root: Path,
    found: Iterable[OversizedFile],
    baseline: set[str],
    baseline_file: str | None,
) -> list[Violation]:
    """Report oversized files the baseline doesn't list, and listed files now fixed."""
    found = list(found)
    violations = [
        Violation(
            RULE_ID,
            CHECK_NAME,
            f"{oversized.path} has {oversized.line_count} lines, over the "
            f"{oversized.line_limit}-line limit for {_code_kind(oversized.path)}",
            SPLIT_FIX,
        )
        for oversized in found
        if oversized.path not in baseline
    ]
    still_oversized = {oversized.path for oversized in found}
    violations.extend(
        Violation(
            RULE_ID,
            CHECK_NAME,
            _stale_baseline_message(root, path),
            f"remove it from {baseline_file} and lower the rule's baseline count",
        )
        for path in sorted(baseline - still_oversized)
    )
    return violations


def run_check(root: Path = REPO_ROOT) -> list[Violation]:
    """Load the rule from the registry under ``root`` and measure the tree."""
    registry, violations = load_registry(root)
    if registry is None:
        return violations
    rule = registry.rule(RULE_ID)
    if rule is None:
        return [
            Violation(
                None,
                CHECK_NAME,
                f"rules/registry.toml has no rule {RULE_ID}",
                "register the rule",
            )
        ]
    excluded_patterns = [exception.path for exception in rule.exceptions]
    baseline_file = rule.baseline.file if rule.baseline is not None else None
    return compare(
        root,
        oversized_files(root, excluded_patterns),
        baseline_paths(root, baseline_file),
        baseline_file,
    )


def check() -> list[str]:
    """Adapter for scripts/run_quality_guards.py."""
    return [str(violation) for violation in run_check(REPO_ROOT)]
