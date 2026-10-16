"""Compare ratchets against the base branch: baselines may only shrink."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from scripts.rules.load import REGISTRY_PATH, load_text
from scripts.rules.model import Registry, Status, Violation

if TYPE_CHECKING:
    from pathlib import Path


class BaseUnavailable(Exception):
    """The base ref could not be read."""


def default_base_ref() -> str | None:
    """Return ``origin/<GITHUB_BASE_REF>`` on a pull-request run, otherwise None."""
    base = os.environ.get("GITHUB_BASE_REF")
    return f"origin/{base}" if base else None


def load_base_registry(root: Path, ref: str) -> Registry | None:
    """Return the registry as it is on ``ref``, or None if the base has none yet.

    Raise BaseUnavailable when ``ref`` does not name a commit.
    """
    verify = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if verify.returncode != 0:
        raise BaseUnavailable(ref)
    shown = subprocess.run(
        ["git", "show", f"{ref}:{REGISTRY_PATH.as_posix()}"],
        cwd=root,
        capture_output=True,
        text=True,
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
                        'add [rule.downgrade] reason = "..." so the downgrade is explicit and reviewable',
                    )
                )
    for rule_id in sorted(current_ids - {rule.id for rule in base.rules}):
        notes.append(f"rule {rule_id} is new")
    return violations, notes
