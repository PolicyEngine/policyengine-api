"""Run repository quality guards."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.guards import migration_contracts  # noqa: E402
from scripts.rules import ci_scripts  # noqa: E402
from scripts.rules import guard as rules_guard  # noqa: E402

Guard = tuple[str, Callable[[], list[str]]]

GUARDS: tuple[Guard, ...] = (
    ("migration-contracts", migration_contracts.check),
    ("rules-registry", rules_guard.check),
    ("ci-scripts", ci_scripts.check),
)


def main() -> int:
    """Run every guard, print its violations, and return 1 if any guard failed."""
    failed = False
    for name, check in GUARDS:
        violations = check()
        if not violations:
            print(f"{name}: passed")  # noqa: T201  # the guard runner reports each result
            continue

        failed = True
        print(f"{name}: failed")  # noqa: T201  # the guard runner reports each result
        for violation in violations:
            print(f"  - {violation}")  # noqa: T201  # the guard runner reports each result

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
