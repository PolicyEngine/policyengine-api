"""The suppressions quality guard: every noqa and type: ignore is explained.

A ``noqa``, ``ruff: disable`` or ``type: ignore`` comment switches ruff or mypy
off for a line, a range of lines or a whole file, so it must say what it
switches off and why:

- a ``noqa`` comment, line-level or file-level (``# ruff: noqa``,
  ``# flake8: noqa``), lists its ruff codes;
- a range suppression, ``# ruff: disable[CODE]``, and ruff's trailing
  ``# ruff: ignore[CODE]`` (a preview feature in ruff 0.15) list their ruff
  codes in brackets;
- a ``type: ignore`` comment lists its mypy error codes in brackets;
- the comment also holds a reason, a ``#`` part that is neither a suppression
  nor another tool's directive (``fmt: skip``, ``pragma: no cover``):
  ``# noqa: CODE  # reason`` or ``# type: ignore[code]  # reason``.

Other tools' comments that switch a check off (``# mypy: ignore-errors``,
``# isort: skip_file``) are not checked.

Only real comments count: the guard reads each tracked ``.py`` and ``.pyi`` file
with ``tokenize``, so a string that looks like a suppression isn't one.

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
import subprocess
import tokenize
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

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
# One part of a comment (the text between two #) that is a suppression. Ruff
# reads the word noqa case-insensitively, but its prefixes for a whole file
# only in lowercase. A range suppression (the disable form with codes in
# brackets) switches its codes off until the matching enable form. Mypy reads
# its ignore comment only in lowercase, and allows spaces before the bracketed
# codes; it treats brackets that hold no code, such as [] or [,], as ignoring
# every error on the line.
_NOQA = re.compile(r"(?:(?:ruff|flake8)\s*:\s*)?(?i:noqa)\b(?P<rest>.*)")
_NOQA_CODES = re.compile(r"\s*:\s*[A-Z]+[0-9]+", re.IGNORECASE)
# The range form, and ruff's trailing ignore[CODE] form (a preview feature in
# ruff 0.15), both list their codes in brackets.
_RUFF_BRACKETED = re.compile(r"ruff\s*:\s*(?:disable|ignore)\b(?P<rest>.*)")
# CPython and mypy read these only at the start of a comment, with no space
# before the colon. Any other text after the prefix is a type comment.
_TYPE_IGNORE = re.compile(r"type:\s*ignore\b(?P<rest>.*)")
_TYPE_COMMENT = re.compile(r"type:\s*\S")
_BRACKETED_CODES = re.compile(r"\s*\[(?P<codes>[^\]]*)\]")
# Other tools' directives, which aren't reasons when they share a comment with
# a suppression. Each pattern matches a whole directive in its tool's syntax,
# so that a reason that starts with a tool's name and a colon still counts.
_OTHER_DIRECTIVES = tuple(
    re.compile(pattern)
    for pattern in (
        r"fmt:\s*(?:skip|off|on)\s*$",
        r"(?i:pragma)[:\s]?\s*(?i:no)\s*(?i:cover|branch)\b",
        r"pyright:\s*(?:ignore(?:\[[^\]]*\])?|basic|standard|strict"
        r"|report\w+\s*=\s*\S+(?:\s*,\s*report\w+\s*=\s*\S+)*)\s*$",
        r"mypy:\s*[\w-]+(?:\s*=\s*\S+)?(?:\s*,\s*[\w-]+(?:\s*=\s*\S+)?)*\s*$",
        r"isort:\s*(?:skip_file|skip|off|on|split)\s*$",
        r"isort:\s*dont-add-imports?\b.*$",
        r"pylint:\s*(?:disable-next|disable|enable|skip-file)"
        r"(?:\s*=\s*[\w-]+(?:\s*,\s*[\w-]+)*)?\s*$",
        r"ruff\s*:\s*(?:enable\s*\[[^\]]*\]|isort\s*:\s*(?:skip_file|skip|off|on|split))"
        r"\s*$",
        r"type:\s*ignore\b",
        r"ty:\s*ignore(?:\[[^\]]*\])?\s*$",
        r"pyrefly:\s*ignore(?:\[[^\]]*\])?\s*$",
        r"pyre-(?:ignore|fixme)(?:\[[^\]]*\])?(?::.*)?$",
        r"pytype:\s*(?:disable|enable)=[\w,-]+\s*$",
        r"yapf:\s*(?:disable|enable)\s*$",
        r"nosec(?:\s+[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*)?\s*$",
        r"nosemgrep(?::\s*[\w.,\s-]+)?$",
        r"NOSONAR\b.*$",
        r"noinspection\s+\w+(?:\s*,\s*\w+)*\s*$",
        r"codespell:\s*ignore\b.*$",
    )
)
SOURCE_SUFFIXES = (".py", ".pyi")
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


def _brackets_name_a_code(rest: str) -> bool:
    codes = _BRACKETED_CODES.match(rest)
    return codes is not None and any(
        code.strip() for code in codes.group("codes").split(",")
    )


def _suppression_has_code(part: str, *, first: bool) -> bool | None:
    """Return whether ``part`` names its codes, or None if it isn't a suppression.

    A type: ignore counts only as the comment's ``first`` part, as mypy reads it.
    """
    noqa = _NOQA.match(part)
    if noqa is not None:
        return _NOQA_CODES.match(noqa.group("rest")) is not None
    ruff_bracketed = _RUFF_BRACKETED.match(part)
    if ruff_bracketed is not None:
        return _brackets_name_a_code(ruff_bracketed.group("rest"))
    type_ignore = _TYPE_IGNORE.match(part) if first else None
    if type_ignore is not None:
        return _brackets_name_a_code(type_ignore.group("rest"))
    return None


def _is_reason(part: str, *, first: bool) -> bool:
    """Whether a part that isn't a suppression is a reason, not a directive."""
    if first and _TYPE_COMMENT.match(part):
        return False
    return not any(directive.match(part) for directive in _OTHER_DIRECTIVES)


def comment_problems(comment: str) -> tuple[str, ...]:
    """Return what a comment's suppressions lack: ``a code``, ``a reason``, both.

    A comment without a suppression lacks nothing. The comment is split at each
    ``#``; a part that is neither a suppression nor another tool's directive
    (such as ``fmt: skip`` or ``pragma: no cover``) and has text is the reason.
    """
    parts = [part.strip() for part in comment.split("#") if part.strip()]
    suppressions = []
    has_reason = False
    for index, part in enumerate(parts):
        named = _suppression_has_code(part, first=index == 0)
        if named is not None:
            suppressions.append(named)
        elif _is_reason(part, first=index == 0):
            has_reason = True
    if not suppressions:
        return ()
    missing = []
    if not all(suppressions):
        missing.append(CODE)
    if not has_reason:
        missing.append(REASON)
    return tuple(missing)


def unexplained_suppressions(path: str, text: str) -> list[Suppression]:
    """Return the suppressions in Python source ``text`` that lack a code or reason.

    Raise SyntaxError when ``text`` doesn't tokenize.
    """
    # tokenize numbers lines at \n, \r\n and \r only; str.splitlines() would
    # also split at form feeds and other separators and misnumber them.
    text = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
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


def tracked_sources(root: Path) -> list[str]:
    """Return the tracked ``.py`` and ``.pyi`` files, or every one in a plain tree.

    A directory that isn't a git checkout (a test's temporary tree) has every
    such file under it scanned.
    """
    if not (root / ".git").exists():
        return sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.suffix in SOURCE_SUFFIXES
        )
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", *(f"*{suffix}" for suffix in SOURCE_SUFFIXES)],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")
    return sorted(path for path in listed if path and (root / path).is_file())


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
    for path in tracked_sources(root):
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
