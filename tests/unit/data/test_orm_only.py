"""Guards for rule api.data.orm-only (rules/registry.toml).

Code that reads or writes database rows declares tables only as SQLAlchemy ORM
mapped classes, SQLModel classes included, and runs every statement through an
ORM Session against them. docs/engineering/skills/alembic-migrations.md
explains the rule under "Database statements through the ORM", with the way to
write each kind of statement. The checks live in orm_access_support.py.

A finding fails unless one of the rule's ``no-orm-form`` [[rule.exception]]
entries names its module, in ``match`` its source and, when the entry gives
one, in ``function`` the function it is in. An entry that names no finding
fails too. The rule's ``migration-revision`` entry takes ``migrations/`` out of
the check.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.rules.load import load_registry
from tests.unit.data.orm_access_support import (
    CORE_CONNECTION,
    CORE_TABLE_DECLARATION,
    RAW_SQL,
    UNMAPPED_TABLE,
    Finding,
    exception_problems,
    orm_access_findings,
    undeclared_findings,
    unmapped_table_findings,
    unmapped_tables_in_packages,
    unscanned_files,
    unused_exceptions,
)

if TYPE_CHECKING:
    from types import ModuleType

    import pytest

    from scripts.rules.model import Rule, RuleException

PROJECT_ROOT = Path(__file__).parents[3]
RULE_ID = "api.data.orm-only"
RULE_DOC = (
    "docs/engineering/skills/alembic-migrations.md#database-statements-through-the-orm"
)
FIXTURES_ROOT = PROJECT_ROOT / "rules" / "fixtures" / RULE_ID
# The directories the rule covers: its scope in rules/registry.toml.
SCANNED_DIRECTORIES = ("policyengine_api", "scripts", "tests", ".github")
# The directories the rule test reads: the scanned ones and migrations/, which
# the rule's migration-revision exception takes out again.
READ_DIRECTORIES = (*SCANNED_DIRECTORIES, "migrations")
# The packages that declare tables, and the test modules that write rows. Every
# table they hold needs a mapped class.
TABLE_PACKAGES = ("policyengine_api.data",)
ROW_HELPER_MODULES = (
    "tests.integration.catalog_rows",
    "tests.integration.simulation_rows",
    "tests.integration.stored_report_rows",
    "tests.unit.v2.sqlite_report_rows",
)


def _declared_site(exception: RuleException) -> str:
    """Describe what an exception names: its file, its match and its function."""
    site = f"{exception.path}: {exception.match}"
    return site if exception.function is None else f"{site} in {exception.function}"


@cache
def _rule() -> Rule:
    registry, violations = load_registry(PROJECT_ROOT)
    assert registry is not None, violations
    rule = registry.rule(RULE_ID)
    assert rule is not None, f"rules/registry.toml has no rule {RULE_ID}"
    return rule


def _relative_name(source_file: Path) -> str:
    return source_file.relative_to(PROJECT_ROOT).as_posix()


@cache
def _read_files() -> tuple[str, ...]:
    """Return every Python file under READ_DIRECTORIES, as relative paths."""
    return tuple(
        _relative_name(source_file)
        for directory in READ_DIRECTORIES
        for source_file in sorted((PROJECT_ROOT / directory).rglob("*.py"))
    )


def _scanned_files() -> list[str]:
    """Return the files the rule checks: those read, less the unscanned ones."""
    unscanned = unscanned_files(_rule().exceptions, PROJECT_ROOT)
    return [file for file in _read_files() if file not in unscanned]


@cache
def _repository_findings() -> tuple[Finding, ...]:
    sources = {
        file: (PROJECT_ROOT / file).read_text(encoding="utf-8")
        for file in _scanned_files()
    }
    return tuple(orm_access_findings(sources))


def _load_fixture(fixture_name: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    path = FIXTURES_ROOT / fixture_name
    spec = importlib.util.spec_from_file_location(f"orm_only_{path.stem}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # SQLAlchemy resolves a mapped class's annotations in its module, which it
    # finds in sys.modules.
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _fixture_findings(fixture_name: str) -> list[tuple[int, str, str]]:
    fixture = FIXTURES_ROOT / fixture_name
    findings = orm_access_findings({fixture_name: fixture.read_text(encoding="utf-8")})
    return [(finding.line, finding.check, finding.source) for finding in findings]


def test_database_code_uses_only_the_orm() -> None:
    findings = _repository_findings()
    exceptions = _rule().exceptions

    problems = [str(finding) for finding in undeclared_findings(findings, exceptions)]
    problems.extend(
        f"declared exception names no finding, remove it: {_declared_site(exception)}"
        for exception in unused_exceptions(findings, exceptions)
    )

    assert problems == [], (
        "Code reaches the database without the ORM; use a mapped class and a "
        f"Session ({RULE_DOC}). For a .table finding on converted code, name the "
        "attribute after what it holds, such as model"
    )


def test_every_table_is_mapped_by_a_class() -> None:
    row_helpers = [importlib.import_module(name) for name in ROW_HELPER_MODULES]

    findings = [
        *unmapped_tables_in_packages(TABLE_PACKAGES, PROJECT_ROOT),
        *unmapped_table_findings(row_helpers, PROJECT_ROOT),
    ]

    assert [str(finding) for finding in findings] == []


def test_orm_only_exceptions_match_a_finding_and_name_a_category() -> None:
    exceptions = _rule().exceptions

    problems = exception_problems(exceptions, _read_files(), PROJECT_ROOT)
    problems.extend(
        f"exception names no finding: {_declared_site(exception)}"
        for exception in unused_exceptions(_repository_findings(), exceptions)
    )

    assert problems == []


def test_every_scanned_directory_contributes_files() -> None:
    scanned = _scanned_files()

    unscanned_directories = [
        directory
        for directory in SCANNED_DIRECTORIES
        if not any(file.startswith(f"{directory}/") for file in scanned)
    ]

    assert unscanned_directories == []
    assert _rule().scope == tuple(
        f"{directory}/**/*.py" for directory in SCANNED_DIRECTORIES
    )


def test_rule_proof_orm_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proof for rule api.data.orm-only (rules/registry.toml)."""
    assert _fixture_findings("bad_simulation_rows.py") == [
        (25, CORE_CONNECTION, "sqlalchemy.Connection"),
        (27, CORE_TABLE_DECLARATION, "sa.Table('stage_catalog_models', ...)"),
        (29, CORE_TABLE_DECLARATION, "sa.MetaData()"),
        (30, CORE_TABLE_DECLARATION, "sa.Column('id', ...)"),
        (31, CORE_TABLE_DECLARATION, "sa.Column('name', ...)"),
        (39, CORE_CONNECTION, "connection.execute(...)"),
        (
            40,
            RAW_SQL,
            "text(f'INSERT INTO {table} ({columns}) VALUES ({placeholders})')",
        ),
        (62, CORE_CONNECTION, "connection.execute(...)"),
        (63, RAW_SQL, "text(f'DELETE FROM {table} WHERE id = :id')"),
    ]
    assert _fixture_findings("good_simulation_rows.py") == []
    bad_module = _load_fixture("bad_simulation_rows.py", monkeypatch)
    good_module = _load_fixture("good_simulation_rows.py", monkeypatch)
    assert [
        (finding.check, finding.source)
        for finding in unmapped_table_findings([bad_module], PROJECT_ROOT)
    ] == [(UNMAPPED_TABLE, "stage_catalog_models")]
    assert unmapped_table_findings([good_module], PROJECT_ROOT) == []
