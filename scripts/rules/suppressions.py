"""The suppressions quality guard: every noqa and type: ignore is explained.

An inline suppression switches a checker off for one line, or for a whole file,
so it must say what it switches off and why:

- a ``noqa`` comment, line-level or file-level (``# ruff: noqa``,
  ``# flake8: noqa``), lists its ruff codes;
- a ``type: ignore`` comment lists its mypy error codes in brackets;
- the comment also holds a reason, a ``#`` part that isn't a suppression:
  ``# noqa: CODE  # reason`` or ``# type: ignore[code]  # reason``.

Only real comments count: the guard reads each tracked Python file with
``tokenize``, so a string that looks like a suppression isn't one.

While the rule is ratcheted, its baseline file lists the tolerated
suppressions, one ``<path> :: <source line>`` per occurrence (a file with two
identical lines lists the entry twice). A suppression the baseline doesn't
list fails, and so does a listed one that is gone or now explained, so the
baseline only shrinks.

Whether a suppression should exist at all is the judgment rule
api.process.agents-suppress-as-last-resort. The rule:
docs/engineering/skills/rules-registry.md#inline-suppressions. Standard library
only.
"""

from __future__ import annotations

import io
import re
import tokenize
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.rules.file_length import tracked_python_files
from scripts.rules.load import load_registry
from scripts.rules.model import Violation

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
RULE_ID = "api.quality.suppressions-explained"
CHECK_NAME = "suppressions"
SEPARATOR = " :: "
CODE = "a code"
REASON = "a reason"
# One part of a comment (the text between two #) that is a suppression. ruff
# reads noqa and its file-level forms case-insensitively.
_NOQA = re.compile(r"(?:(?:ruff|flake8)\s*:\s*)?noqa\b(?P<rest>.*)", re.IGNORECASE)
_NOQA_CODES = re.compile(r"\s*:\s*[A-Z]+[0-9]+", re.IGNORECASE)
_TYPE_IGNORE = re.compile(r"type\s*:\s*ignore\b(?P<rest>.*)", re.IGNORECASE)
_TYPE_IGNORE_CODES = re.compile(r"\[\s*[^\]\s][^\]]*\]")
FIX = (
    "name what it suppresses and say why, as `# noqa: CODE  # reason` or "
    "`# type: ignore[code]  # reason`, once a code change or a setting can't "
    "remove the finding (api.process.agents-suppress-as-last-resort; "
    "docs/engineering/skills/rules-registry.md#inline-suppressions)"
)


@dataclass(frozen=True)
class Suppression:
    """A suppression comment that names no code, gives no reason, or both."""

    path: str
    line: int
    comment: str
    source_line: str
    missing: tuple[str, ...]

    @property
    def entry(self) -> str:
        """The suppression as a baseline entry: ``<path> :: <source line>``."""
        return f"{self.path}{SEPARATOR}{self.source_line.strip()}"


def _suppression_has_code(part: str) -> bool | None:
    """Return whether ``part`` names its codes, or None if it isn't a suppression."""
    noqa = _NOQA.match(part)
    if noqa is not None:
        return _NOQA_CODES.match(noqa.group("rest")) is not None
    type_ignore = _TYPE_IGNORE.match(part)
    if type_ignore is not None:
        return _TYPE_IGNORE_CODES.match(type_ignore.group("rest")) is not None
    return None


def comment_problems(comment: str) -> tuple[str, ...]:
    """Return what a comment's suppressions lack: ``a code``, ``a reason``, both.

    A comment without a suppression lacks nothing. The comment is split at each
    ``#``; a part that isn't a suppression and has text is the reason.
    """
    parts = [part.strip() for part in comment.split("#")]
    has_code = [_suppression_has_code(part) for part in parts if part]
    suppressions = [named for named in has_code if named is not None]
    if not suppressions:
        return ()
    missing = []
    if not all(suppressions):
        missing.append(CODE)
    if len(suppressions) == len(has_code):
        missing.append(REASON)
    return tuple(missing)


def unexplained_suppressions(path: str, text: str) -> list[Suppression]:
    """Return the suppressions in Python source ``text`` that lack a code or reason.

    Raise SyntaxError when ``text`` doesn't tokenize.
    """
    lines = text.splitlines()
    found = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except tokenize.TokenError as error:
        raise SyntaxError(str(error)) from error
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        missing = comment_problems(token.string)
        if missing:
            line = token.start[0]
            found.append(
                Suppression(path, line, token.string, lines[line - 1], missing)
            )
    return found


def _describe(suppression: Suppression) -> str:
    gaps = {
        (CODE,): "names no code",
        (REASON,): "gives no reason",
        (CODE, REASON): "names no code and gives no reason",
    }
    return (
        f"{suppression.path}:{suppression.line}: `{suppression.comment.strip()}` "
        f"{gaps[suppression.missing]}"
    )


def compare(
    found: Iterable[Suppression], baseline: Iterable[str], baseline_file: str | None
) -> list[Violation]:
    """Report suppressions the baseline doesn't list, and listed ones now gone.

    Each baseline line tolerates one occurrence of its entry.
    """
    found = list(found)
    allowed = Counter(baseline)
    present = Counter(suppression.entry for suppression in found)
    violations = []
    seen: Counter[str] = Counter()
    for suppression in found:
        seen[suppression.entry] += 1
        if seen[suppression.entry] > allowed[suppression.entry]:
            violations.append(
                Violation(RULE_ID, CHECK_NAME, _describe(suppression), FIX)
            )
    for entry in sorted(allowed):
        violations.extend(
            Violation(
                RULE_ID,
                CHECK_NAME,
                f"baseline entry no longer applies: {entry}",
                f"remove it from {baseline_file} and lower the rule's baseline count",
            )
            for _ in range(allowed[entry] - present[entry])
        )
    return violations


def _baseline_lines(root: Path, baseline_file: str | None) -> list[str]:
    """Read the baseline's entries, one per line, keeping repeated entries."""
    if baseline_file is None or not (root / baseline_file).is_file():
        return []
    return [
        line.strip()
        for line in (root / baseline_file).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def run_check(root: Path = REPO_ROOT) -> list[Violation]:
    """Load the rule from the registry under ``root`` and scan every Python file."""
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
    violations = []
    found = []
    for path in tracked_python_files(root):
        text = (root / path).read_text(encoding="utf-8", errors="replace")
        try:
            found.extend(unexplained_suppressions(path, text))
        except SyntaxError:
            violations.append(
                Violation(
                    RULE_ID,
                    CHECK_NAME,
                    f"{path} doesn't tokenize, so its suppressions can't be checked",
                    "fix the syntax error (ruff check reports it)",
                )
            )
    baseline_file = rule.baseline.file if rule.baseline is not None else None
    return [
        *violations,
        *compare(found, _baseline_lines(root, baseline_file), baseline_file),
    ]


def check() -> list[str]:
    """Adapter for scripts/run_quality_guards.py."""
    return [str(violation) for violation in run_check(REPO_ROOT)]
