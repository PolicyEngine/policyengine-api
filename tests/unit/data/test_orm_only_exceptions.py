"""Unit tests for rule api.data.orm-only's exceptions.

They test how a ``no-orm-form`` exception names findings, by file, source and
function, the ``<module>`` marker, which entries need a function, the
``migration-revision`` path exceptions, the problems ``exception_problems``
reports, and the function each finding records. test_orm_access_support.py
tests what the checks report.
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from scripts.rules.model import RuleException
from tests.unit.data.orm_access_examples import SESSION_FACTORY, STORE
from tests.unit.data.orm_access_support import (
    MIGRATION_REVISION,
    NO_ORM_FORM,
    RAW_SQL,
    Finding,
    exception_problems,
    orm_access_findings,
    undeclared_findings,
    unscanned_files,
    unused_exceptions,
)

if TYPE_CHECKING:
    from pathlib import Path


def _finding(
    file: str, source: str, line: int = 1, *, function: str | None = None
) -> Finding:
    return Finding(file, line, RAW_SQL, source, function=function)


def _construct_exception(
    path: str, match: str | None, *, function: str | None = None
) -> RuleException:
    return RuleException(
        path=path,
        reason="no ORM form",
        match=match,
        category=NO_ORM_FORM,
        function=function,
    )


def test_each_finding_names_the_function_it_is_in() -> None:
    source = """
    import sqlalchemy as sa

    module_statement = sa.text("SELECT 1")

    def reconcile():
        return sa.text("SELECT 2")

    class Reconciler:
        class_statement = sa.text("SELECT 3")

        def apply(self):
            def build():
                return sa.text("SELECT 4")

            return sa.text("SELECT 5")

    async def read():
        return sa.text("SELECT 6")
    """

    findings = orm_access_findings({STORE: dedent(source)})

    assert [(finding.source, finding.function) for finding in findings] == [
        ("sa.text('SELECT 1')", None),
        ("sa.text('SELECT 2')", "reconcile"),
        ("sa.text('SELECT 3')", "Reconciler"),
        ("sa.text('SELECT 4')", "Reconciler.apply.build"),
        ("sa.text('SELECT 5')", "Reconciler.apply"),
        ("sa.text('SELECT 6')", "read"),
    ]


def test_a_finding_in_a_function_names_it_when_described() -> None:
    in_function = _finding(STORE, "text(statement)", line=3, function="apply_grants")

    assert str(in_function) == f"{STORE}:3: raw SQL: text(statement) in apply_grants"
    assert str(_finding(STORE, "text(statement)", line=3)) == (
        f"{STORE}:3: raw SQL: text(statement)"
    )


def test_an_exception_with_a_function_allows_findings_only_in_that_function() -> None:
    granting = _finding(STORE, "text(statement)", line=3, function="apply_grants")
    reading = _finding(STORE, "text(statement)", line=9, function="read_roles")
    module_level = _finding(STORE, "text(statement)", line=12)
    exceptions = [
        _construct_exception(STORE, "text(statement)", function="apply_grants")
    ]

    assert undeclared_findings([granting, reading, module_level], exceptions) == [
        reading,
        module_level,
    ]


def test_an_exception_with_a_function_is_unused_without_a_finding_there() -> None:
    findings = [_finding(STORE, "text(statement)", function="read_roles")]
    in_its_function = _construct_exception(
        STORE, "text(statement)", function="read_roles"
    )
    elsewhere = _construct_exception(STORE, "text(statement)", function="apply_grants")
    anywhere_in_the_module = _construct_exception(STORE, "text(statement)")

    assert unused_exceptions(
        findings, [in_its_function, elsewhere, anywhere_in_the_module]
    ) == [elsewhere]


def test_an_exception_allows_every_finding_with_its_file_and_source() -> None:
    set_role = "text(f'SET ROLE {role}')"
    findings = [
        _finding(STORE, set_role, line=3),
        _finding(STORE, set_role, line=9),
        _finding(STORE, "text('RESET ROLE')", line=12),
        _finding(SESSION_FACTORY, set_role, line=4),
    ]
    exceptions = [_construct_exception(STORE, set_role)]

    assert undeclared_findings(findings, exceptions) == [
        _finding(STORE, "text('RESET ROLE')", line=12),
        _finding(SESSION_FACTORY, set_role, line=4),
    ]


def test_an_exception_that_names_no_finding_is_unused() -> None:
    findings = [_finding(STORE, "text('RESET ROLE')")]
    used = _construct_exception(STORE, "text('RESET ROLE')")
    other_file = _construct_exception(SESSION_FACTORY, "text('RESET ROLE')")
    other_source = _construct_exception(STORE, "text('SET ROLE owner')")
    path_exception = RuleException(
        path="migrations/**/*.py", reason="revisions", category=MIGRATION_REVISION
    )

    assert unused_exceptions(
        findings, [used, other_file, other_source, path_exception]
    ) == [other_file, other_source]


def test_a_path_exception_takes_its_files_out_of_the_check(tmp_path: Path) -> None:
    for file in ("migrations/v2/env.py", "migrations/v2/versions/one.py", "app.py"):
        (tmp_path / file).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / file).write_text("", encoding="utf-8")
    exceptions = [
        RuleException(
            path="migrations/**/*.py", reason="revisions", category=MIGRATION_REVISION
        ),
        _construct_exception("app.py", "text('SELECT 1')"),
    ]

    assert unscanned_files(exceptions, tmp_path) == {
        "migrations/v2/env.py",
        "migrations/v2/versions/one.py",
    }


def test_exception_problems_name_each_unusable_exception(tmp_path: Path) -> None:
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "env.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "store.py").write_text("", encoding="utf-8")
    exceptions = [
        _construct_exception("tests/store.py", "text('SELECT 1')"),
        _construct_exception("tests/store.py", None),
        _construct_exception("tests/missing.py", "text('SELECT 1')"),
        RuleException(
            path="migrations/*.py", reason="revisions", category=MIGRATION_REVISION
        ),
        RuleException(
            path="migrations/*.py",
            reason="revisions",
            match="text('SELECT 1')",
            category=MIGRATION_REVISION,
        ),
        RuleException(
            path="scripts/*.py", reason="scripts", category=MIGRATION_REVISION
        ),
        RuleException(path="tests/store.py", reason="no category"),
        RuleException(path="tests/store.py", reason="driver", category="driver-access"),
    ]

    assert exception_problems(
        exceptions, ["migrations/env.py", "tests/store.py"], tmp_path
    ) == [
        "exception for tests/store.py names no construct: set match to the "
        "finding's source",
        "exception for tests/missing.py must name one existing file",
        "exception for migrations/*.py skips whole files, so it takes no match",
        "exception for scripts/*.py matches no file the rule test reads: remove it",
        "exception for tests/store.py has unknown category None: use one of "
        "['no-orm-form', 'migration-revision']",
        "exception for tests/store.py has unknown category 'driver-access': use "
        "one of ['no-orm-form', 'migration-revision']",
    ]


def _needs_function_problem(path: str, match: str) -> str:
    return (
        f"exception for {path} ({match}) needs a function: set function to the "
        "enclosing function of its finding, or to <module> for a finding at "
        "module level"
    )


def test_exceptions_outside_tests_or_naming_no_sql_text_need_a_function(
    tmp_path: Path,
) -> None:
    """Production entries, and entries whose match holds no SQL, name a function.

    An entry whose match is a bare call, a call on variables or an attribute
    read would otherwise allow every such call in the module.
    """
    for file in ("policyengine_api/store.py", "scripts/migrate.py", "tests/rows.py"):
        (tmp_path / file).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / file).write_text("", encoding="utf-8")
    store, script, rows = (
        "policyengine_api/store.py",
        "scripts/migrate.py",
        "tests/rows.py",
    )
    exceptions = [
        _construct_exception(store, "sa.text(f'ANALYZE {tables}')"),
        _construct_exception(store, "text(statement)", function="apply_grants"),
        _construct_exception(script, "session.connection()"),
        _construct_exception(rows, "text(statement)"),
        _construct_exception(rows, "session.get_bind()"),
        _construct_exception(rows, "mapper.local_table"),
        _construct_exception(rows, "session.get_bind()", function="Rows.dialect"),
        _construct_exception(rows, "text(f'TRUNCATE {tables} CASCADE')"),
        _construct_exception(
            rows, "sqlite_connection.execute('PRAGMA foreign_keys = ON')"
        ),
    ]

    assert exception_problems(exceptions, [], tmp_path) == [
        _needs_function_problem(store, "sa.text(f'ANALYZE {tables}')"),
        _needs_function_problem(script, "session.connection()"),
        _needs_function_problem(rows, "text(statement)"),
        _needs_function_problem(rows, "session.get_bind()"),
        _needs_function_problem(rows, "mapper.local_table"),
    ]


@pytest.mark.parametrize(
    "match",
    [
        "sqlite3.connect(':memory:')",
        "psycopg.connect('postgresql://localhost/policyengine')",
        "sa.Column('id', ...)",
        "Table('household_jobs', ...)",
        "event.listen(engine, 'connect')",
        "text(f'{statement}')",
        "text(f'{statement} {parameters}')",
        "connection.execute(f'{statement}')",
        "text('')",
    ],
)
def test_a_test_entry_naming_no_sql_statement_needs_a_function(
    tmp_path: Path, match: str
) -> None:
    """Only raw SQL text, or a statement method given SQL, names one statement.

    A string given to anything else, or an f-string of names alone, names no
    statement, so the entry would allow the call wherever its module makes it.
    """
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "rows.py").write_text("", encoding="utf-8")
    exceptions = [_construct_exception("tests/rows.py", match)]

    assert exception_problems(exceptions, [], tmp_path) == [
        _needs_function_problem("tests/rows.py", match)
    ]


@pytest.mark.parametrize(
    "match",
    [
        "text('TRUNCATE reports')",
        "sa.text(f'TRUNCATE {tables} CASCADE')",
        "sa.TextClause('SELECT 1')",
        "sa.literal_column('count(*)')",
        "DDL('DROP TABLE reports')",
        "sqlite_connection.execute('PRAGMA foreign_keys = ON')",
        "connection.exec_driver_sql('BEGIN IMMEDIATE')",
        "session.connection().exec_driver_sql(f'EXPLAIN {expanded.statement}', ...)",
        "conn.scalar('SELECT 1')",
    ],
)
def test_a_test_entry_naming_one_sql_statement_needs_no_function(
    tmp_path: Path, match: str
) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "rows.py").write_text("", encoding="utf-8")
    exceptions = [_construct_exception("tests/rows.py", match)]

    assert exception_problems(exceptions, [], tmp_path) == []


def test_a_module_level_exception_allows_findings_only_at_module_level() -> None:
    """``function = "<module>"`` names the module's own top-level statements."""
    module_level = _finding(STORE, "text('ANALYZE reports')", line=3)
    in_function = _finding(STORE, "text('ANALYZE reports')", line=9, function="analyze")
    exceptions = [
        _construct_exception(STORE, "text('ANALYZE reports')", function="<module>")
    ]

    assert undeclared_findings([module_level, in_function], exceptions) == [in_function]


def test_a_module_level_exception_is_unused_without_a_module_level_finding() -> None:
    findings = [_finding(STORE, "text('ANALYZE reports')", function="analyze")]
    module_level = _construct_exception(
        STORE, "text('ANALYZE reports')", function="<module>"
    )

    assert unused_exceptions(findings, [module_level]) == [module_level]


def test_a_production_entry_may_name_module_level_as_its_function(
    tmp_path: Path,
) -> None:
    (tmp_path / "policyengine_api").mkdir()
    (tmp_path / "policyengine_api" / "store.py").write_text("", encoding="utf-8")
    exceptions = [
        _construct_exception(
            "policyengine_api/store.py", "text(statement)", function="<module>"
        )
    ]

    assert exception_problems(exceptions, [], tmp_path) == []


def test_a_path_exception_takes_no_function(tmp_path: Path) -> None:
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "env.py").write_text("", encoding="utf-8")
    exceptions = [
        RuleException(
            path="migrations/*.py",
            reason="revisions",
            category=MIGRATION_REVISION,
            function="run_migrations_online",
        )
    ]

    assert exception_problems(exceptions, ["migrations/env.py"], tmp_path) == [
        "exception for migrations/*.py skips whole files, so it takes no function"
    ]


def test_an_exception_for_one_constant_statement_allows_no_other() -> None:
    source = """
    import sqlalchemy

    sqlite_connection.execute("PRAGMA foreign_keys = ON")
    sqlite_connection.execute("DELETE FROM reports")
    """
    findings = orm_access_findings({STORE: dedent(source)})
    exceptions = [
        _construct_exception(
            STORE, "sqlite_connection.execute('PRAGMA foreign_keys = ON')"
        )
    ]

    assert [
        finding.source for finding in undeclared_findings(findings, exceptions)
    ] == ["sqlite_connection.execute('DELETE FROM reports')"]
