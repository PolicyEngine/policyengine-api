"""Run repository quality guards."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.guards import migration_contracts  # noqa: E402


Guard = tuple[str, Callable[[], list[str]]]

GUARDS: tuple[Guard, ...] = (("migration-contracts", migration_contracts.check),)


def main() -> int:
    failed = False
    for name, check in GUARDS:
        violations = check()
        if not violations:
            print(f"{name}: passed")
            continue

        failed = True
        print(f"{name}: failed")
        for violation in violations:
            print(f"  - {violation}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
