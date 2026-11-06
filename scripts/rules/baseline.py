"""Compare ratchets against the base branch: baselines may only shrink."""

from __future__ import annotations

import os
import subprocess
from collections import Counter
from typing import TYPE_CHECKING

from scripts.rules.load import REGISTRY_PATH, load_text
from scripts.rules.model import Registry, Status, Violation
from scripts.rules.validate import baseline_entry_lines

if TYPE_CHECKING:
    from pathlib import Path


class BaseUnavailableError(Exception):
    """The base ref could not be read."""


def default_base_ref() -> str | None:
    """Return the git revision to compare with, if there is one.

    That is RULES_BASE_REF as given, which make quality-check sets to the
    commit the branch shares with its base branch; otherwise
    ``origin/<GITHUB_BASE_REF>`` on a pull-request run; otherwise None.
    """
    explicit = os.environ.get("RULES_BASE_REF")
    if explicit:
        return explicit
    base = os.environ.get("GITHUB_BASE_REF")
    return f"origin/{base}" if base else None


def load_base_registry(root: Path, ref: str) -> Registry | None:
    """Return the registry as it is on ``ref``, or None if the base has none yet.

    Raise BaseUnavailableError when ``ref`` does not name a commit.
    """
    verify = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if verify.returncode != 0:
        raise BaseUnavailableError(ref)
    shown = subprocess.run(
        ["git", "show", f"{ref}:{REGISTRY_PATH.as_posix()}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if shown.returncode != 0:
        return None
    registry, _ = load_text(shown.stdout)
    return registry


def check_baselines(
    current: Registry, base: Registry
) -> tuple[list[Violation], list[str]]:
    """Return (violations, notes)."""
    violations: list[Violation] = []
    notes: list[str] = []
    current_ids = {rule.id for rule in current.rules}
    for old in base.rules:
        new = current.rule(old.id)
        if new is None:
            notes.append(f"rule {old.id} was removed")
            continue
        if old.baseline and new.baseline and new.baseline.count > old.baseline.count:
            violations.append(
                Violation(
                    new.id,
                    "baseline",
                    f"baseline grew from {old.baseline.count} to {new.baseline.count}",
                    "fix the new violations instead of adding them to the baseline",
                )
            )
        weaker = (Status.ADVISORY, Status.DOC_ONLY)
        if old.status in (Status.ENFORCED, Status.RATCHETED) and new.status in weaker:
            if new.downgrade_reason:
                notes.append(
                    f"rule {new.id} downgraded to {new.status}: {new.downgrade_reason}"
                )
            else:
                violations.append(
                    Violation(
                        new.id,
                        "baseline",
                        f"status weakened from {old.status} to {new.status}",
                        'add [rule.downgrade] reason = "..." so the downgrade is '
                        "explicit and reviewable",
                    )
                )
    notes.extend(
        f"rule {rule_id} is new"
        for rule_id in sorted(current_ids - {rule.id for rule in base.rules})
    )
    return violations, notes


def _entries_at(root: Path, ref: str, path: str) -> Counter[str] | None:
    """Return a baseline file's entries, counted, as on ``ref``; None if absent."""
    shown = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if shown.returncode != 0:
        return None
    return Counter(baseline_entry_lines(shown.stdout))


def check_baseline_entries(
    root: Path, current: Registry, base: Registry, ref: str
) -> list[Violation]:
    """Report baseline entries that the base branch's copy of the file lacks.

    A baseline may only shrink, so an entry can't be swapped for a new one at
    the same count. Entries are counted, because a baseline may list an entry
    once per tolerated occurrence: listing it more often than the base branch
    does fails too. A rule or baseline file that is new on this branch has
    nothing to compare against.
    """
    violations = []
    for old in base.rules:
        new = current.rule(old.id)
        if new is None or old.baseline is None or new.baseline is None:
            continue
        before = _entries_at(root, ref, old.baseline.file)
        current_file = root / new.baseline.file
        if before is None or not current_file.is_file():
            continue
        after = Counter(baseline_entry_lines(current_file.read_text(encoding="utf-8")))
        added = [
            entry
            if before[entry] == 0
            else f"{entry} ({after[entry]} times, the base branch {before[entry]})"
            for entry in sorted(after)
            if after[entry] > before[entry]
        ]
        if added:
            violations.append(
                Violation(
                    new.id,
                    "baseline",
                    f"{new.baseline.file} lists entries the base branch's copy "
                    f"doesn't: {', '.join(added)}",
                    "fix the new violations instead of adding them to the baseline",
                )
            )
    return violations
