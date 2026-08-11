"""Report whether a pull request changes the API v1 Alembic surface."""

from __future__ import annotations

import subprocess
import sys
from pathlib import PurePosixPath


EXACT_PATHS = frozenset(
    {
        "alembic-v1.ini",
        ".github/workflows/alembic-v1-check.yml",
        "docs/engineering/skills/alembic-migrations.md",
        "policyengine_api/data/v1_models.py",
        "pyproject.toml",
        "scripts/v1_alembic_changes.py",
        "scripts/v1_database_migration.py",
        "scripts/write_v1_database_urls.py",
        "tests/integration/test_alembic_mysql_lifecycle.py",
        "tests/integration/test_v1_schema_metadata_compatibility.py",
        "tests/unit/test_alembic_workflows.py",
        "uv.lock",
    }
)
PATH_PREFIXES = (
    "migrations/v1/",
    "tests/unit/data/test_alembic_",
    "tests/unit/data/test_v1_database_migration",
)


def is_v1_alembic_path(path: str) -> bool:
    """Return whether *path* can change v1 migration behavior."""

    normalized = PurePosixPath(path).as_posix().removeprefix("./")
    return normalized in EXACT_PATHS or normalized.startswith(PATH_PREFIXES)


def changed_paths(base: str, head: str) -> tuple[str, ...]:
    """Return repository paths changed between two git revisions."""

    result = subprocess.run(
        ["git", "diff", "--name-only", base, head, "--"],
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(path for path in result.stdout.splitlines() if path)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: v1_alembic_changes.py BASE HEAD", file=sys.stderr)
        return 2

    changed = any(is_v1_alembic_path(path) for path in changed_paths(*args))
    print(f"changed={str(changed).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
