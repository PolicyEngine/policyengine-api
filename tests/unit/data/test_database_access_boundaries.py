"""Guards for rule api.data.sqlalchemy-and-alembic-only (rules/registry.toml).

Non-test code reaches relational databases only through SQLAlchemy engines,
connections and sessions, and changes persistent schema only through Alembic
revisions. The rule's exceptions are its [[rule.exception]] entries in
rules/registry.toml, which these tests read: each names a module and the one
construct it may use, or a path pattern (the Alembic revisions) the check
doesn't scan. docs/engineering/skills/alembic-migrations.md explains them under
"Database access through SQLAlchemy and Alembic".

Like the api.data.runtime-sql-confined guard in test_runtime_sql_boundaries.py,
these tests walk the source tree, collect offenders and compare them with the
expected set. They parse each module with ast so that comments and docstrings
are not mistaken for imports, calls or SQL.
"""

from __future__ import annotations

import ast
import re
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from policyengine_api.data.v2.catalog.publication_staging import STAGING_METADATA
from scripts.rules.file_length import is_excluded
from scripts.rules.load import load_registry

if TYPE_CHECKING:
    from scripts.rules.model import RuleException

PROJECT_ROOT = Path(__file__).parents[3]
NON_TEST_ROOTS = ("policyengine_api", "scripts", "migrations", ".github")
RULE_DOC = (
    "docs/engineering/skills/alembic-migrations.md"
    "#database-access-through-sqlalchemy-and-alembic"
)
PROOF_FIXTURES = "rules/fixtures/api.data.sqlalchemy-and-alembic-only"

DATABASE_DRIVER_MODULES = (
    "psycopg",
    "psycopg2",
    "pymysql",
    "MySQLdb",
    "mysql.connector",
    "sqlite3",
    "asyncpg",
    "pg8000",
    "aiosqlite",
    "aiomysql",
)
# Attributes and methods that hand out the driver connection beneath a
# SQLAlchemy connection or engine.
DRIVER_CONNECTION_ATTRIBUTES = frozenset({"driver_connection", "dbapi_connection"})
DRIVER_CONNECTION_METHODS = frozenset({"raw_connection"})
# Private attributes of a driver connection, such as pymysql's socket, whether
# read as an attribute or through getattr(connection, "_sock", ...).
DRIVER_PRIVATE_ATTRIBUTES = frozenset({"_sock"})

SCHEMA_COLLECTION_METHODS = frozenset({"create_all", "drop_all"})
SCHEMA_OBJECT_METHODS = frozenset({"create", "drop"})
SCHEMA_OBJECT_CONSTRUCTORS = frozenset({"Table", "Index", "Sequence"})
SCHEMA_OBJECT_COLLECTIONS = frozenset({"tables", "sorted_tables"})
DDL_CONSTRUCTORS = frozenset(
    {
        "DDL",
        "CreateTable",
        "DropTable",
        "CreateIndex",
        "DropIndex",
        "CreateSchema",
        "DropSchema",
        "CreateSequence",
        "DropSequence",
        "AddConstraint",
        "DropConstraint",
    }
)
ALEMBIC_OPERATION_MODULES = ("alembic.op", "alembic.operations")
ALEMBIC_OPERATION_RECEIVERS = frozenset({"op", "alembic.op"})
# A schema-changing statement at the start of a string, of a line in it, or
# after a semicolon. Anchoring to a statement start keeps ordinary messages
# such as "failed to create table rows" from matching.
SCHEMA_CHANGING_SQL = re.compile(
    r"(?:^|;)\s*("
    r"(?:CREATE(?:\s+OR\s+REPLACE)?"
    r"(?:\s+(?:GLOBAL|LOCAL|MATERIALIZED|TEMP|TEMPORARY|UNIQUE|UNLOGGED))*"
    r"|ALTER|DROP)"
    r"\s+(?:DATABASE|EXTENSION|INDEX|SCHEMA|SEQUENCE|TABLE|TYPE|VIEW)"
    r"|TRUNCATE"
    r")\b",
    re.IGNORECASE | re.MULTILINE,
)

RULE_ID = "api.data.sqlalchemy-and-alembic-only"
# The rule's [[rule.exception]] entries in rules/registry.toml, by category:
# - driver-access: one driver import or driver-connection access, named by
#   its path and, in match, the construct find_driver_access reports;
# - schema-change: one schema change, named the same way for
#   find_schema_changes;
# - migration-revision: a path pattern this check doesn't scan at all.
DRIVER_ACCESS_CATEGORY = "driver-access"
SCHEMA_CHANGE_CATEGORY = "schema-change"
UNSCANNED_CATEGORY = "migration-revision"
CONSTRUCT_CATEGORIES = (DRIVER_ACCESS_CATEGORY, SCHEMA_CHANGE_CATEGORY)


@cache
def rule_exceptions() -> tuple[RuleException, ...]:
    """Return the rule's [[rule.exception]] entries from rules/registry.toml."""
    registry, violations = load_registry(PROJECT_ROOT)
    assert registry is not None, violations
    rule = registry.rule(RULE_ID)
    assert rule is not None, f"rules/registry.toml has no rule {RULE_ID}"
    return rule.exceptions


def declared_constructs(category: str) -> frozenset[tuple[str, str]]:
    """Return the (module, construct) pairs the registry allows in ``category``."""
    return frozenset(
        (exception.path, exception.match)
        for exception in rule_exceptions()
        if exception.category == category and exception.match is not None
    )


def unscanned_patterns() -> tuple[str, ...]:
    """Return the path patterns the registry takes out of this check entirely."""
    return tuple(
        exception.path
        for exception in rule_exceptions()
        if exception.category == UNSCANNED_CATEGORY
    )


class DatabaseAccessFinding(NamedTuple):
    """One construct a check reports, with where it occurs."""

    module_path: str
    line_number: int
    construct: str

    @property
    def declaration(self) -> tuple[str, str]:
        """The (module, construct) pair an allowlist entry declares."""
        return (self.module_path, self.construct)


def _python_modules(project_root: Path) -> list[str]:
    """Return every Python module under NON_TEST_ROOTS outside a tests directory."""
    return [
        module_file.relative_to(project_root).as_posix()
        for root_name in NON_TEST_ROOTS
        for module_file in sorted((project_root / root_name).rglob("*.py"))
        if "tests" not in module_file.relative_to(project_root).parts[:-1]
    ]


def non_test_python_modules(project_root: Path = PROJECT_ROOT) -> list[str]:
    """Return every non-test Python module the rule covers, as relative paths.

    Tests are excluded, and so are the paths the rule's migration-revision
    exceptions in rules/registry.toml name: the generated Alembic revisions.
    """
    patterns = unscanned_patterns()
    module_paths = [
        module_path
        for module_path in _python_modules(project_root)
        if not is_excluded(module_path, patterns)
    ]
    assert module_paths, f"no Python modules found under {NON_TEST_ROOTS}"
    return module_paths


def _read_module(module_path: str) -> str:
    return (PROJECT_ROOT / module_path).read_text(encoding="utf-8")


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _is_driver_module(qualified_name: str) -> bool:
    return any(
        qualified_name == driver_module
        or qualified_name.startswith(f"{driver_module}.")
        for driver_module in DATABASE_DRIVER_MODULES
    )


def _imported_names(node: ast.AST) -> list[str]:
    """Fully qualified names an import statement or import call brings in."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [f"{node.module}.{alias.name}" for alias in node.names]
    if (
        isinstance(node, ast.Call)
        and _called_name(node) in {"import_module", "__import__"}
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return [node.args[0].value]
    return []


def _driver_access_constructs(node: ast.AST) -> list[str]:
    constructs = [
        f"import {imported_name}"
        for imported_name in _imported_names(node)
        if _is_driver_module(imported_name)
    ]
    if isinstance(node, ast.Attribute) and node.attr in (
        DRIVER_CONNECTION_ATTRIBUTES | DRIVER_PRIVATE_ATTRIBUTES
    ):
        constructs.append(f"attribute .{node.attr}")
    if (
        isinstance(node, ast.Call)
        and _called_name(node) == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value in DRIVER_PRIVATE_ATTRIBUTES
    ):
        constructs.append(f"attribute .{node.args[1].value}")
    if isinstance(node, ast.Call) and _called_name(node) in DRIVER_CONNECTION_METHODS:
        constructs.append(f"call .{_called_name(node)}()")
    return constructs


def find_driver_access(
    source_text: str, module_path: str
) -> list[DatabaseAccessFinding]:
    """Report every direct database-driver import or driver-connection access.

    Covers import statements, importlib.import_module and __import__ calls
    naming a driver module, the driver_connection and dbapi_connection
    attributes, raw_connection() calls, and a driver connection's private
    attributes (pymysql's ``_sock``), read directly or through getattr.
    """
    return [
        DatabaseAccessFinding(module_path, node.lineno, construct)
        for node in ast.walk(ast.parse(source_text))
        for construct in _driver_access_constructs(node)
    ]


def _assigned_names(assignment: ast.Assign | ast.AnnAssign) -> set[str]:
    targets = (
        assignment.targets
        if isinstance(assignment, ast.Assign)
        else [assignment.target]
    )
    return {target.id for target in targets if isinstance(target, ast.Name)}


def _schema_object_names(tree: ast.Module) -> set[str]:
    """Names bound to a Table, Index or Sequence, or to a loop over tables.

    A name counts when it is assigned a Table(...), Index(...) or
    Sequence(...) call, assigned a tuple or list of such names, or is the
    target of a loop over one of those collections or over a metadata's
    tables or sorted_tables.
    """
    bindings = [
        (_assigned_names(node), node.value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    object_names = {
        bound_name
        for bound_names, assigned_value in bindings
        if isinstance(assigned_value, ast.Call)
        and _called_name(assigned_value) in SCHEMA_OBJECT_CONSTRUCTORS
        for bound_name in bound_names
    }
    collection_names = {
        bound_name
        for bound_names, assigned_value in bindings
        if isinstance(assigned_value, (ast.Tuple, ast.List, ast.Set))
        and any(
            isinstance(element, ast.Name) and element.id in object_names
            for element in assigned_value.elts
        )
        for bound_name in bound_names
    }
    for node in ast.walk(tree):
        if not isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            continue
        if not isinstance(node.target, ast.Name):
            continue
        iterates_over_tables = any(
            (isinstance(part, ast.Attribute) and part.attr in SCHEMA_OBJECT_COLLECTIONS)
            or (isinstance(part, ast.Name) and part.id in collection_names)
            for part in ast.walk(node.iter)
        )
        if iterates_over_tables:
            object_names.add(node.target.id)
    return object_names


def _targets_schema_object(call: ast.Call, schema_object_names: set[str]) -> bool:
    """Whether a create() or drop() call acts on a table, index or sequence."""
    if any(keyword.arg == "checkfirst" for keyword in call.keywords):
        return True
    if not isinstance(call.func, ast.Attribute):
        return False
    receiver = call.func.value
    if isinstance(receiver, ast.Attribute) and receiver.attr == "__table__":
        return True
    if (
        isinstance(receiver, ast.Subscript)
        and isinstance(receiver.value, ast.Attribute)
        and receiver.value.attr in SCHEMA_OBJECT_COLLECTIONS
    ):
        return True
    return isinstance(receiver, ast.Name) and receiver.id in schema_object_names


def _schema_call_constructs(
    call: ast.Call,
    schema_object_names: set[str],
    *,
    outside_migrations: bool,
) -> list[str]:
    called_name = _called_name(call)
    if called_name in DDL_CONSTRUCTORS:
        return [f"construct {called_name}()"]
    if not isinstance(call.func, ast.Attribute):
        return []
    receiver = ast.unparse(call.func.value)
    if called_name in SCHEMA_COLLECTION_METHODS or (
        called_name in SCHEMA_OBJECT_METHODS
        and _targets_schema_object(call, schema_object_names)
    ):
        return [f"call {receiver}.{called_name}()"]
    if outside_migrations and receiver in ALEMBIC_OPERATION_RECEIVERS:
        return [f"call {receiver}.{called_name}()"]
    return []


def _alembic_operation_imports(node: ast.AST) -> list[str]:
    return [
        f"import {imported_name}"
        for imported_name in _imported_names(node)
        if any(
            imported_name == module_name or imported_name.startswith(f"{module_name}.")
            for module_name in ALEMBIC_OPERATION_MODULES
        )
    ]


def _docstring_node_ids(tree: ast.Module) -> set[int]:
    docstring_ids = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        first_statement = node.body[0] if node.body else None
        if (
            isinstance(first_statement, ast.Expr)
            and isinstance(first_statement.value, ast.Constant)
            and isinstance(first_statement.value.value, str)
        ):
            docstring_ids.add(id(first_statement.value))
    return docstring_ids


def find_schema_changes(
    source_text: str, module_path: str
) -> list[DatabaseAccessFinding]:
    """Report every schema change a module makes outside an Alembic revision.

    Covers create_all() and drop_all(); create() and drop() on a table, index
    or sequence; SQLAlchemy DDL constructs such as CreateTable; Alembic
    operations (op.*) outside migrations/; and string literals, other than
    docstrings, that start a CREATE, ALTER or DROP of a table, type, schema,
    database, index, sequence, view or extension, or a TRUNCATE.
    """
    tree = ast.parse(source_text)
    outside_migrations = not module_path.startswith("migrations/")
    schema_object_names = _schema_object_names(tree)
    docstring_ids = _docstring_node_ids(tree)
    findings = []
    for node in ast.walk(tree):
        constructs: list[str] = []
        if isinstance(node, ast.Call):
            constructs.extend(
                _schema_call_constructs(
                    node,
                    schema_object_names,
                    outside_migrations=outside_migrations,
                )
            )
        if outside_migrations:
            constructs.extend(_alembic_operation_imports(node))
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstring_ids
        ):
            constructs.extend(
                "SQL text " + " ".join(statement.group(1).upper().split())
                for statement in SCHEMA_CHANGING_SQL.finditer(node.value)
            )
        findings.extend(
            DatabaseAccessFinding(module_path, node.lineno, construct)
            for construct in constructs
        )
    return findings


def _assert_only_declared(
    findings: list[DatabaseAccessFinding],
    declared: frozenset[tuple[str, str]],
    description: str,
) -> None:
    """Fail on any undeclared finding and on any declaration nothing needs."""
    undeclared = sorted(
        finding for finding in findings if finding.declaration not in declared
    )
    unused_declarations = sorted(
        declared - {finding.declaration for finding in findings}
    )
    problems = [
        f"{finding.module_path}:{finding.line_number}: {finding.construct}"
        for finding in undeclared
    ]
    problems.extend(
        f"declared exception no longer needed, remove it: {module_path}: {construct}"
        for module_path, construct in unused_declarations
    )
    assert not problems, (
        f"{description} outside the declared exceptions (see {RULE_DOC}):\n"
        + "\n".join(problems)
    )


def test_rule_exceptions_name_a_known_category_and_what_they_allow() -> None:
    """Each exception names a construct in one file, or a pattern never scanned."""
    exceptions = rule_exceptions()
    assert exceptions, f"{RULE_ID} has no [[rule.exception]] entries"
    problems = []
    for exception in exceptions:
        where = f"exception for {exception.path}"
        if exception.category in CONSTRUCT_CATEGORIES:
            if exception.match is None:
                problems.append(f"{where} names no construct: set match")
            if not (PROJECT_ROOT / exception.path).is_file():
                problems.append(f"{where} must name one existing file")
        elif exception.category == UNSCANNED_CATEGORY:
            if exception.match is not None:
                problems.append(f"{where} skips whole files, so it takes no match")
            if not any(
                is_excluded(module_path, (exception.path,))
                for module_path in _python_modules(PROJECT_ROOT)
            ):
                problems.append(f"{where} matches no module: remove it")
        else:
            problems.append(
                f"{where} has unknown category {exception.category!r}: use one of "
                f"{[*CONSTRUCT_CATEGORIES, UNSCANNED_CATEGORY]}"
            )
    assert not problems, "\n".join(problems)


def test_non_test_code_reaches_database_drivers_only_where_declared() -> None:
    findings = [
        finding
        for module_path in non_test_python_modules()
        for finding in find_driver_access(_read_module(module_path), module_path)
    ]
    _assert_only_declared(
        findings,
        declared_constructs(DRIVER_ACCESS_CATEGORY),
        "Direct database-driver access",
    )


def test_non_test_code_changes_schema_only_through_alembic() -> None:
    findings = [
        finding
        for module_path in non_test_python_modules()
        for finding in find_schema_changes(_read_module(module_path), module_path)
    ]
    _assert_only_declared(
        findings,
        declared_constructs(SCHEMA_CHANGE_CATEGORY),
        "Schema change outside Alembic",
    )


def test_publication_staging_tables_are_temporary_and_dropped_at_commit() -> None:
    assert STAGING_METADATA.tables, "STAGING_METADATA declares no staging tables"
    for table in STAGING_METADATA.tables.values():
        create_statement = str(
            CreateTable(table).compile(dialect=postgresql.dialect())
        ).strip()
        assert create_statement.startswith(f"CREATE TEMPORARY TABLE {table.name} "), (
            f"staging table {table.name} must be TEMPORARY"
        )
        assert create_statement.endswith("ON COMMIT DROP"), (
            f"staging table {table.name} must be dropped at commit"
        )


def test_rule_proof_sqlalchemy_and_alembic_only() -> None:
    """Proof for rule api.data.sqlalchemy-and-alembic-only (rules/registry.toml)."""
    bad_fixture = f"{PROOF_FIXTURES}/bad_database_access.py"
    good_fixture = f"{PROOF_FIXTURES}/good_database_access.py"
    bad_source = _read_module(bad_fixture)
    good_source = _read_module(good_fixture)

    bad_driver_access = find_driver_access(bad_source, bad_fixture)
    bad_schema_changes = find_schema_changes(bad_source, bad_fixture)
    assert {finding.construct for finding in bad_driver_access} == {
        "import psycopg",
        "attribute ._sock",
    }
    assert {finding.construct for finding in bad_schema_changes} == {
        "call V1Base.metadata.create_all()"
    }

    assert find_driver_access(good_source, good_fixture) == []
    assert find_schema_changes(good_source, good_fixture) == []
