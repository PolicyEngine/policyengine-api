"""Checks behind rule api.data.orm-only in rules/registry.toml.

Code that reads or writes database rows declares tables only as SQLAlchemy ORM
mapped classes, SQLModel classes included, and runs every statement through an
ORM Session against them. ``orm_access_findings`` reads source, so the rule
test in ``test_orm_only.py`` runs it on the repository and the proof test runs
it on the fixtures under ``rules/fixtures/api.data.orm-only/``.
``unmapped_table_findings`` reports every table that given modules hold and no
mapped class maps, and ``unmapped_tables_in_packages`` imports whole packages
for it, which finds tables built in ways the source checks can't see.
``undeclared_findings`` and ``unused_exceptions`` compare the findings with the
rule's ``[[rule.exception]]`` entries. docs/engineering/skills/
alembic-migrations.md explains the rule under "Database statements through the
ORM", with the way to write each kind of statement.

This is a port of the checker behind sim.persistence.orm-only in
PolicyEngine/policyengine-sim-api
(``projects/policyengine-simulation-entry/tests/orm_access_support.py``). It
differs in four ways:

- SQLModel is the ORM here, so importing it is not a finding, and SQLModel
  table classes are mapped classes. SQLModel re-exports SQLAlchemy's names,
  so a name imported from ``sqlmodel`` counts as the SQLAlchemy name it
  re-exports: ``from sqlmodel import text`` is raw SQL and ``from sqlmodel
  import create_engine`` creates an engine.
- The modules that may create or hold an Engine are the named
  ``SESSION_FACTORY_MODULES``, and the modules that may build ``MetaData`` are
  the named ``DECLARATIVE_BASE_MODULES``, rather than files matched by name.
- A session-factory module may also import ``Connection``, open a Connection
  (``connect()``, ``connection()``, ``get_bind()`` and ``begin()`` on an
  engine), open a database driver's connection and attach listeners for
  pool, engine or dialect events, which no other module may do.
  ``raw_connection()`` hands out the driver's connection, not SQLAlchemy's,
  and is reported in every module.
- A finding is allowed when a ``no-orm-form`` exception names its file, in
  ``match`` its ``source`` and, when the exception gives one, in ``function``
  the function it is in, or ``<module>`` for module level; a
  ``migration-revision`` exception names a path pattern the rule test doesn't
  read. Each finding records the innermost class or function whose body holds
  it.

The source checks look for Core rather than for the ORM, so any statement on
mapped classes passes. Each file is checked on its own, through its own imports:
``from sqlalchemy import text`` and ``import sqlalchemy as sa`` both count, and
a ``text``, ``Table`` or ``update`` from another package doesn't. A Core table is
reported where it starts: where it is declared, where it is read from a mapped
class, mapper or MetaData or as the bare name ``__table__``, and where an
annotation names ``Table`` or ``TableClause``, apart from a class's bare
``__table__`` annotation in a declarative-base module. Its later uses aren't
reported, because the rule has no baseline and the first finding already fails
it.

A public function of a session-factory module may not return an Engine or
Connection, and only a session-factory module may read ``factory.kw["bind"]``.
A statement run outside a session is reported with its constant arguments, as
in ``connection.execute('PRAGMA foreign_keys = ON')``, so an exception can name
that one statement. ``.connection()``, ``.get_bind()``, ``.raw_connection()``
and ``.exec_driver_sql()`` are SQLAlchemy's names and count whatever a module
imports, as does opening a connection of psycopg, psycopg2, pymysql, sqlite3 or
mysql.connector: a call into one of them, followed through the module's
imports, whose last name is ``connect`` or ``Connect``, or ends with
``Connection``. An exception in a test module needs no ``function`` when its
match is raw SQL text, or a statement method, whose first argument holds a
statement keyword outside its SQL comments. The rules that go by a
method or attribute name other libraries share apply only in modules that
import sqlalchemy or sqlmodel: any ``.table`` read, ``kw["bind"]``,
``.execute()`` on anything not named as a session, ``.scalar()``,
``.scalars()``, ``.stream()`` and ``.stream_scalars()`` on a name such as
``connection``, and the ``.connect()``, ``.begin()`` and ``.cursor()`` calls.

The checks guard against ordinary Core use, not against deliberate evasion. They
don't see imports made through ``importlib`` or ``__import__``, engines or
connections passed around without an ``Engine`` or ``Connection`` annotation, so
a connection held under a name such as ``session`` isn't reported, a statement
method passed without being called, a function that returns an engine with no
return annotation, the engine an ``Inspector`` holds in ``bind`` or ``engine``, a
quoted name inside an annotation such as ``Optional["Table"]``, ``Table`` under
another local name such as ``Jobs = Table``, names from ``from sqlalchemy import
*``, a ``.table`` read in a module that doesn't import sqlalchemy or sqlmodel, a
statement run on an open driver connection in such a module, a Session's
``bind`` attribute, or an event listener whose target and event name aren't its
first two positional arguments, the name a string literal. ``.tables`` of a
MetaData isn't reported when the name holding it doesn't end in ``metadata``
and wasn't assigned ``MetaData(...)``. Imports are read for the whole module,
not for each scope, so a local name that shadows one, such as a parameter
named ``sqlite3``, is still taken for the import.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping
    from types import ModuleType

    from sqlalchemy.orm import registry

    from scripts.rules.model import RuleException

SQLALCHEMY_MODULE = "sqlalchemy"
SQLMODEL_MODULE = "sqlmodel"
# The libraries whose names the checks follow. SQLModel re-exports
# SQLAlchemy's, under the same names.
ORM_LIBRARY_MODULES = (SQLALCHEMY_MODULE, SQLMODEL_MODULE)
# Core's table declarations, the lightweight table() and column() included.
# MetaData may be built only in a declarative-base module, as the metadata of
# one of the library's DeclarativeBase classes.
TABLE_CONSTRUCTORS = frozenset(
    {"Column", "ColumnClause", "MetaData", "Table", "TableClause", "column", "table"}
)
TABLE_TYPES = frozenset({"Table", "TableClause"})
# A declarative base's classes may annotate what each of them maps.
MAPPED_TABLE_ATTRIBUTE = "__table__"
METADATA_CONSTRUCTOR = "MetaData"
# The modules that may build MetaData: the v1 declarative base, the v2 models'
# metadata (SQLModel's, with its naming convention), and the publication staging
# tables' own declarative base, which keeps them out of the v2 metadata Alembic
# compares.
DECLARATIVE_BASE_MODULES = frozenset(
    {
        "policyengine_api/data/v1_models.py",
        "policyengine_api/data/v2/models/__init__.py",
        "policyengine_api/data/v2/catalog/publication_staging_base.py",
    }
)
# The modules that may create and hold an engine, open a Connection and attach
# pool events, to hand out Session factories: API v1's (with the listeners
# that record its pool's events), API v2's and the tests'.
SESSION_FACTORY_MODULES = frozenset(
    {
        "policyengine_api/data/orm.py",
        "policyengine_api/data/orm_pool_events.py",
        # API v1's Session factories for commands that run once; unlike orm.py,
        # importing it loads no .env file, Cloud SQL connector or pool listeners.
        "policyengine_api/data/v1_sessions.py",
        "policyengine_api/data/v2/database.py",
        "tests/fixtures/database_sessions.py",
        # The tests of orm_pool_events drive the pool it listens to: they
        # invalidate, detach and recycle connections and hold two at once,
        # which no Session offers. Their statements still run in Sessions.
        "tests/unit/data/test_orm_pool_events.py",
        # The pool event tests' fake database driver: it opens the in-memory
        # SQLite connections, shaped like pymysql's, that their engine pools.
        "tests/unit/data/fake_driver_connections.py",
    }
)
ENGINE_NAMES = frozenset(
    {
        "AsyncEngine",
        "Engine",
        "create_async_engine",
        "create_engine",
        "engine_from_config",
    }
)
CONNECTION_NAMES = frozenset({"AsyncConnection", "Connection"})
ENGINE_FACTORIES = frozenset({"create_async_engine", "create_engine"})
ENGINE_TYPES = frozenset({"AsyncEngine", "Engine"})
# A name such as engine or simulation_engine, but not policyengine.
ENGINE_NAME_PATTERN = re.compile(r"(?:^|_)engine$", re.IGNORECASE)
# Calls that open a Connection, which only a session-factory module may make.
# connection() and get_bind() are SQLAlchemy's names, so they count in every
# module; connect() and begin() on an engine count only beside sqlalchemy,
# because other libraries share those names.
SESSION_CONNECTION_METHODS = frozenset({"connection", "get_bind"})
CONNECT_METHOD = "connect"
ENGINE_TRANSACTION_METHOD = "begin"
# The call that hands out the driver's connection beneath SQLAlchemy's, which
# no module may make.
DRIVER_CONNECTION_METHODS = frozenset({"raw_connection"})
# The database drivers, and how their calls that open a connection end: a
# connect function or method, as in psycopg.connect or
# psycopg.Connection.connect, or a connection class, whose name ends with
# Connection, as in sqlite3.Connection or psycopg2.extras.RealDictConnection.
# Only a session-factory module may make them.
DATABASE_DRIVER_MODULES = (
    "mysql.connector",
    "psycopg",
    "psycopg2",
    "pymysql",
    "sqlite3",
)
DRIVER_CONNECT_FUNCTIONS = frozenset({"Connect", "connect"})
DRIVER_CONNECTION_CLASS_SUFFIX = "Connection"
# execute runs only on a name such as session or store_session, which finds a
# connection passed around without a Connection annotation. A Result has scalar
# and scalars too, so the others are reported only on a name such as connection.
EXECUTE_METHOD = "execute"
SESSION_NAME_PATTERN = re.compile(r"(?:^|_)session$", re.IGNORECASE)
CONNECTION_STATEMENT_METHODS = frozenset(
    {"scalar", "scalars", "stream", "stream_scalars"}
)
CONNECTION_NAME_PATTERN = re.compile(r"(?:^|_)(?:connection|conn)$", re.IGNORECASE)
# What a session-factory module keeps to itself: no public function returns one
# of these, and only it reads the engine out of a sessionmaker's keywords.
HELD_DATABASE_TYPES = ENGINE_TYPES | CONNECTION_NAMES
SESSION_FACTORY_KEYWORDS = "kw"
SESSION_FACTORY_BIND_KEY = "bind"
# event.listen and event.listens_for, with the events of a pool, an engine or
# connection, and a dialect (SQLAlchemy's PoolEvents, ConnectionEvents and
# DialectEvents). Only a session-factory module may listen for them. Session,
# mapper, attribute and DDL events have other names.
EVENT_LISTENER_FUNCTIONS = frozenset({"listen", "listens_for"})
DATABASE_EVENT_NAMES = frozenset(
    {
        # PoolEvents
        "checkin",
        "checkout",
        "close",
        "close_detached",
        "connect",
        "detach",
        "first_connect",
        "invalidate",
        "reset",
        "soft_invalidate",
        # ConnectionEvents
        "after_cursor_execute",
        "after_execute",
        "before_cursor_execute",
        "before_execute",
        "begin",
        "begin_twophase",
        "commit",
        "commit_twophase",
        "engine_connect",
        "engine_disposed",
        "prepare_twophase",
        "release_savepoint",
        "rollback",
        "rollback_savepoint",
        "rollback_twophase",
        "savepoint",
        "set_connection_execution_options",
        "set_engine_execution_options",
        # DialectEvents
        "do_connect",
        "do_execute",
        "do_execute_no_params",
        "do_executemany",
        "do_setinputsizes",
        "handle_error",
    }
)
# Attributes that reach a Core table from a mapped class, its mapper or a
# MetaData, and the ones that do so only on a mapper, inspect() or a MetaData.
TABLE_ATTRIBUTES = frozenset(
    {"__table__", "local_table", "persist_selectable", "sorted_tables"}
)
MAPPER_TABLE_ATTRIBUTES = frozenset({"selectable", "tables"})
MAPPER_FUNCTIONS = frozenset({"class_mapper", "inspect", "object_mapper"})
MAPPER_NAMES = frozenset({"__mapper__", "mapper"})
# A column's or mapped attribute's table, as in HouseholdJob.id.table: read in a
# module that imports sqlalchemy or sqlmodel, any .table is reported.
COLUMN_TABLE_ATTRIBUTE = "table"
METADATA_SUFFIX = "metadata"
RAW_SQL_FUNCTIONS = frozenset({"DDL", "TextClause", "literal_column", "text"})
# exec_driver_sql is SQLAlchemy's name, so it counts in every module; a cursor
# counts only beside sqlalchemy, because every DB-API driver has one.
DRIVER_SQL_METHOD = "exec_driver_sql"
CURSOR_METHOD = "cursor"
# A model's schema details given as SQL text: a server default and a partial
# index's condition, by keyword, and a check constraint's condition.
SCHEMA_DETAIL_KEYWORDS = frozenset(
    {"postgresql_where", "server_default", "server_onupdate", "sqlite_where"}
)
CHECK_CONSTRAINT = "CheckConstraint"

CORE_TABLE_DECLARATION = "Core table declaration"
CORE_TABLE_ACCESS = "Core table access"
CORE_CONNECTION = "Core engine or connection"
RAW_SQL = "raw SQL"
UNMAPPED_TABLE = "table without a mapped class"

# The rule's [[rule.exception]] categories: one construct in one module that
# SQLAlchemy's ORM has no form for, named by the module's path, in match the
# finding's source and, in function, the function it is in; and a path pattern
# the rule test doesn't read at all.
NO_ORM_FORM = "no-orm-form"
MIGRATION_REVISION = "migration-revision"
EXCEPTION_CATEGORIES = (NO_ORM_FORM, MIGRATION_REVISION)
# Outside the tests, every no-orm-form exception names its function, or
# MODULE_LEVEL for a finding in no class or function.
TEST_DIRECTORY = "tests/"
MODULE_LEVEL = "<module>"
# What makes a literal SQL of its own: a statement keyword as a whole word,
# outside a SQL comment (-- to the end of a line, or /* ... */).
SQL_STATEMENT_KEYWORD = re.compile(
    r"\b(?:ALTER|ANALYZE|BEGIN|CALL|COMMENT|COMMIT|COPY|CREATE|DELETE|DO|DROP"
    r"|EXPLAIN|GRANT|INSERT|LOCK|PRAGMA|RESET|REVOKE|ROLLBACK|SAVEPOINT|SELECT"
    r"|SET|SHOW|TRUNCATE|UPDATE|VACUUM|WITH)\b",
    re.IGNORECASE,
)
SQL_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
# The calls whose first argument is SQL: the raw SQL constructs and the methods
# that run a statement. An exception naming one, given SQL of its own, names
# one statement, so it needs no function in a test module.
SQL_TEXT_CALLS = RAW_SQL_FUNCTIONS | {
    DRIVER_SQL_METHOD,
    EXECUTE_METHOD,
    *CONNECTION_STATEMENT_METHODS,
}
SCOPE_NODES = (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)


@dataclass(frozen=True)
class Finding:
    """One place where code reaches the database without the ORM.

    ``function`` is the dotted name of the innermost class or function whose
    body holds it, as in ``Reconciler.apply``, or ``None`` at module level.
    """

    file: str
    line: int
    check: str
    source: str
    function: str | None = None

    def __str__(self) -> str:
        """Describe the finding as ``file:line: check: source in function``."""
        described = f"{self.file}:{self.line}: {self.check}: {self.source}"
        if self.function is None:
            return described
        return f"{described} in {self.function}"


def _matches_module(module_name: str, parent_module: str) -> bool:
    return module_name == parent_module or module_name.startswith(f"{parent_module}.")


def _library_of(module_name: str, libraries: Iterable[str]) -> str | None:
    """Return the one of ``libraries`` that ``module_name`` belongs to, or ``None``."""
    return next(
        (library for library in libraries if _matches_module(module_name, library)),
        None,
    )


def _orm_library(module_name: str) -> str | None:
    """Return the ORM library ``module_name`` belongs to, or ``None``."""
    return _library_of(module_name, ORM_LIBRARY_MODULES)


def _library_imports(tree: ast.Module, libraries: Iterable[str]) -> dict[str, str]:
    """Map each name the module imports from ``libraries`` to its dotted name.

    ``import mysql.connector`` binds ``mysql``, and ``from mysql import
    connector`` binds ``connector`` as ``mysql.connector``.
    """
    libraries = tuple(libraries)
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _library_of(alias.name, libraries) is None:
                    continue
                if alias.asname:
                    imported[alias.asname] = alias.name
                else:
                    top_level = alias.name.split(".", 1)[0]
                    imported[top_level] = top_level
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            for alias in node.names:
                qualified = f"{node.module}.{alias.name}"
                if _library_of(qualified, libraries) is not None:
                    imported[alias.asname or alias.name] = qualified
    return imported


def _orm_library_imports(tree: ast.Module) -> dict[str, str]:
    """Map each name imported from sqlalchemy or sqlmodel to its dotted name."""
    return _library_imports(tree, ORM_LIBRARY_MODULES)


def _qualified_name(node: ast.expr, imported: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return imported.get(node.id)
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value, imported)
        return None if parent is None else f"{parent}.{node.attr}"
    return None


def _library_name(node: ast.expr, imported: Mapping[str, str]) -> str:
    """Return the last part of the ORM library name ``node`` refers to, or ``""``."""
    qualified = _qualified_name(node, imported)
    return qualified.rsplit(".", 1)[-1] if qualified else ""


def _annotation_names(
    annotation: ast.expr | None, imported: Mapping[str, str]
) -> set[str]:
    """Return the ORM library names an annotation refers to, unions included.

    A wholly quoted annotation is parsed. Strings inside one aren't, because
    they may be anything, such as ``Literal`` values or ``Annotated`` metadata.
    """
    if annotation is None:
        return set()
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return set()
    return {
        name
        for node in ast.walk(annotation)
        if isinstance(node, (ast.Name, ast.Attribute))
        and (name := _library_name(node, imported))
    }


def _bound_targets(target: ast.expr) -> list[str]:
    """Return the names and attributes an assignment target binds."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [target.attr]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts for name in _bound_targets(element)]
    return []


def _last_name(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        return _last_name(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


@dataclass
class _Module:
    """One scanned file and the names it imports from the ORM and the drivers."""

    file: str
    tree: ast.Module
    imported: dict[str, str]
    driver_imported: dict[str, str]

    @property
    def uses_sqlalchemy(self) -> bool:
        """Whether the module imports anything from sqlalchemy or sqlmodel."""
        return bool(self.imported)

    @property
    def is_session_factory(self) -> bool:
        return self.file in SESSION_FACTORY_MODULES

    @property
    def is_declarative_base(self) -> bool:
        return self.file in DECLARATIVE_BASE_MODULES


def _annotated_as(module: _Module, types: frozenset[str]) -> set[str]:
    """Return the names and attributes annotated with one of ``types``."""
    names: set[str] = set()
    for node in ast.walk(module.tree):
        if isinstance(node, ast.arg):
            if types & _annotation_names(node.annotation, module.imported):
                names.add(node.arg)
        elif isinstance(node, ast.AnnAssign) and types & _annotation_names(
            node.annotation, module.imported
        ):
            names.update(_bound_targets(node.target))
    return names


def _bound_to_calls(module: _Module, functions: frozenset[str]) -> set[str]:
    """Return the names and attributes bound to a call of one of ``functions``."""
    return {
        name
        for target, value in _assignment_nodes(module.tree)
        if isinstance(value, ast.Call)
        and _library_name(value.func, module.imported) in functions
        for name in _bound_targets(target)
    }


def _paired(target: ast.expr, value: ast.expr) -> Iterator[tuple[ast.expr, ast.expr]]:
    """Pair each part of a tuple target with its value, nested tuples included."""
    if (
        isinstance(target, (ast.Tuple, ast.List))
        and isinstance(value, (ast.Tuple, ast.List))
        and len(target.elts) == len(value.elts)
    ):
        for element, element_value in zip(target.elts, value.elts, strict=True):
            yield from _paired(element, element_value)
    else:
        yield target, value


def _assignment_nodes(tree: ast.AST) -> Iterator[tuple[ast.expr, ast.expr]]:
    """Yield each assignment's target and value, pairing tuples.

    ``a, b = x, y`` yields ``a`` with ``x`` and ``b`` with ``y``.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                yield from _paired(target, node.value)
        elif (
            isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None
        ):
            yield node.target, node.value


def _bound_to_mappers(module: _Module) -> set[str]:
    """Return the names and attributes assigned a mapper, as in ``m = X.__mapper__``."""
    return {
        name
        for target, value in _assignment_nodes(module.tree)
        if isinstance(value, ast.Attribute) and value.attr in MAPPER_NAMES
        for name in _bound_targets(target)
    }


def _call_summary(call: ast.Call) -> str:
    parts = [ast.unparse(call.args[0])] if call.args else []
    if len(call.args) > 1 or call.keywords:
        parts.append("...")
    return f"{ast.unparse(call.func)}({', '.join(parts)})"


def _statement_summary(call: ast.Call) -> str:
    """Summarize a statement call, its constant arguments written out.

    Any other argument, and any keyword, is ``...``, with a run of them written
    once: ``connection.execute('SELECT 1', ...)`` or ``connection.execute(...)``.
    """
    parts: list[str] = []
    for argument in [*call.args, *call.keywords]:
        part = ast.unparse(argument) if isinstance(argument, ast.Constant) else "..."
        if part != "..." or not parts or parts[-1] != "...":
            parts.append(part)
    return f"{ast.unparse(call.func)}({', '.join(parts)})"


def _schema_detail_calls(tree: ast.Module, imported: Mapping[str, str]) -> set[int]:
    """Return the calls given as a default or as an index's or check's condition."""
    details = {
        id(keyword.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg in SCHEMA_DETAIL_KEYWORDS
    }
    details.update(
        id(node.args[0])
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and node.args
        and _library_name(node.func, imported) == CHECK_CONSTRAINT
    )
    return details


@dataclass(frozen=True)
class _ModuleContext:
    module: _Module
    metadata_names: set[str]
    mapper_names: set[str]
    engine_names: set[str]
    schema_details: set[int]
    called: set[int]
    mapped_table_annotations: set[int]


def _forbidden_connection_name(name: str, context: _ModuleContext) -> bool:
    """Whether ``name`` creates or holds an Engine or Connection outside a factory."""
    return (
        name in ENGINE_NAMES or name in CONNECTION_NAMES
    ) and not context.module.is_session_factory


def _import_findings(
    node: ast.Import | ast.ImportFrom, context: _ModuleContext
) -> Iterator[tuple[str, str]]:
    if (
        isinstance(node, ast.Import)
        or node.level
        or node.module is None
        or _orm_library(node.module) is None
    ):
        return
    for alias in node.names:
        if _forbidden_connection_name(alias.name, context):
            yield CORE_CONNECTION, f"{node.module}.{alias.name}"


def _reaches_mapped_table(node: ast.Attribute, context: _ModuleContext) -> bool:
    if node.attr in TABLE_ATTRIBUTES:
        return True
    receiver = node.value
    if node.attr == COLUMN_TABLE_ATTRIBUTE:
        # A column's table is read, never called: sa.table(...) is a function.
        return (
            context.module.uses_sqlalchemy
            and isinstance(node.ctx, ast.Load)
            and id(node) not in context.called
        )
    if node.attr not in MAPPER_TABLE_ATTRIBUTES:
        return False
    if isinstance(receiver, ast.Call):
        function = _library_name(receiver.func, context.module.imported)
        return function in MAPPER_FUNCTIONS
    receiver_name = _last_name(receiver)
    return (
        receiver_name in MAPPER_NAMES
        or receiver_name in context.mapper_names
        or receiver_name in context.metadata_names
        or receiver_name.lower().endswith(METADATA_SUFFIX)
    )


def _attribute_findings(
    node: ast.Attribute, context: _ModuleContext
) -> Iterator[tuple[str, str]]:
    if _reaches_mapped_table(node, context):
        yield CORE_TABLE_ACCESS, ast.unparse(node)
    elif _forbidden_connection_name(
        _library_name(node, context.module.imported), context
    ):
        yield CORE_CONNECTION, str(_qualified_name(node, context.module.imported))


def _runs_raw_sql(node: ast.Call, function: str, context: _ModuleContext) -> bool:
    if function in RAW_SQL_FUNCTIONS:
        return id(node) not in context.schema_details
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr == DRIVER_SQL_METHOD:
        return True
    return context.module.uses_sqlalchemy and node.func.attr == CURSOR_METHOD


def _connects_a_driver(node: ast.Call, context: _ModuleContext) -> bool:
    """Whether a call opens a database driver's connection outside a factory.

    The call is into a driver module, followed through the module's imports,
    and its last name is ``connect`` or ``Connect``, or ends with
    ``Connection``, as a connection class's does.
    """
    if context.module.is_session_factory:
        return False
    qualified = _qualified_name(node.func, context.module.driver_imported)
    if qualified is None or _library_of(qualified, DATABASE_DRIVER_MODULES) is None:
        return False
    last_name = qualified.rsplit(".", 1)[-1]
    return last_name in DRIVER_CONNECT_FUNCTIONS or last_name.endswith(
        DRIVER_CONNECTION_CLASS_SUFFIX
    )


def _opens_engine_connection(method: ast.Attribute, context: _ModuleContext) -> bool:
    """Whether ``connect()``, or ``begin()`` on an engine, opens a Connection.

    Other libraries share these names, so they count only beside sqlalchemy.
    """
    if not context.module.uses_sqlalchemy:
        return False
    if method.attr == CONNECT_METHOD:
        return True
    receiver = _last_name(method.value)
    return method.attr == ENGINE_TRANSACTION_METHOD and (
        receiver in context.engine_names or bool(ENGINE_NAME_PATTERN.search(receiver))
    )


def _opens_connection(node: ast.Call, context: _ModuleContext) -> bool:
    """Whether a call opens a Connection where it may not, or a driver connection."""
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr in DRIVER_CONNECTION_METHODS:
        return True
    if context.module.is_session_factory:
        return False
    return node.func.attr in SESSION_CONNECTION_METHODS or _opens_engine_connection(
        node.func, context
    )


def _database_event_listener(
    node: ast.Call, function: str, context: _ModuleContext
) -> str | None:
    """Describe a pool, engine or dialect event listener outside a factory.

    The summary names the listener function, its target and the event, as in
    ``event.listen(engine, 'connect')``.
    """
    if (
        function not in EVENT_LISTENER_FUNCTIONS
        or context.module.is_session_factory
        # The listener's target, then the event's name.
        or len(node.args) < 2
    ):
        return None
    event_name = node.args[1]
    if not (
        isinstance(event_name, ast.Constant)
        and event_name.value in DATABASE_EVENT_NAMES
    ):
        return None
    target = ast.unparse(node.args[0])
    return f"{ast.unparse(node.func)}({target}, {event_name.value!r})"


def _runs_outside_a_session(node: ast.Call, context: _ModuleContext) -> bool:
    """Whether a statement runs on something other than a session."""
    if not context.module.uses_sqlalchemy or not isinstance(node.func, ast.Attribute):
        return False
    receiver = _last_name(node.func.value)
    if node.func.attr == EXECUTE_METHOD:
        return not SESSION_NAME_PATTERN.search(receiver)
    return node.func.attr in CONNECTION_STATEMENT_METHODS and bool(
        CONNECTION_NAME_PATTERN.search(receiver)
    )


def _call_findings(
    node: ast.Call, context: _ModuleContext
) -> Iterator[tuple[str, str]]:
    function = _library_name(node.func, context.module.imported)
    if function in TABLE_CONSTRUCTORS and not (
        function == METADATA_CONSTRUCTOR and context.module.is_declarative_base
    ):
        yield CORE_TABLE_DECLARATION, _call_summary(node)
    elif _runs_raw_sql(node, function, context):
        yield RAW_SQL, _call_summary(node)
    elif _connects_a_driver(node, context) or _opens_connection(node, context):
        yield CORE_CONNECTION, _call_summary(node)
    elif listener := _database_event_listener(node, function, context):
        yield CORE_CONNECTION, listener
    elif _runs_outside_a_session(node, context):
        yield CORE_CONNECTION, _statement_summary(node)


def _annotation_text(annotation: ast.expr) -> str:
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return annotation.value
    return ast.unparse(annotation)


def _table_annotation_findings(
    label: str, annotation: ast.expr | None, context: _ModuleContext
) -> list[tuple[str, str]]:
    """Report an annotation naming a Core table type, as in ``jobs: Table``."""
    names = _annotation_names(annotation, context.module.imported)
    if annotation is None or not names & TABLE_TYPES:
        return []
    return [(CORE_TABLE_ACCESS, f"{label}{_annotation_text(annotation)}")]


def _class_level_statements(node: ast.ClassDef) -> Iterator[ast.stmt]:
    """Yield a class's own statements, including those under an ``if``."""
    pending: list[ast.stmt] = list(node.body)
    while pending:
        statement = pending.pop()
        yield statement
        if isinstance(statement, ast.If):
            pending.extend([*statement.body, *statement.orelse])


def _mapped_table_annotations(module: _Module) -> set[int]:
    """Return each class's bare ``__table__`` annotation in a declarative base."""
    if not module.is_declarative_base:
        return set()
    return {
        id(statement)
        for node in ast.walk(module.tree)
        if isinstance(node, ast.ClassDef)
        for statement in _class_level_statements(node)
        if isinstance(statement, ast.AnnAssign)
        and statement.value is None
        and isinstance(statement.target, ast.Name)
        and statement.target.id == MAPPED_TABLE_ATTRIBUTE
    }


def _annotated_assignment_findings(
    node: ast.AnnAssign, context: _ModuleContext
) -> list[tuple[str, str]]:
    if id(node) in context.mapped_table_annotations:
        return []
    return _table_annotation_findings(
        f"{ast.unparse(node.target)}: ", node.annotation, context
    )


def _function_findings(
    node: ast.FunctionDef | ast.AsyncFunctionDef, context: _ModuleContext
) -> list[tuple[str, str]]:
    """Report a function returning a Core table, or a factory module's engine."""
    findings = _table_annotation_findings(f"{node.name}() -> ", node.returns, context)
    if not context.module.is_session_factory or node.name.startswith("_"):
        return findings
    returned = _annotation_names(node.returns, context.module.imported)
    return findings + [
        (CORE_CONNECTION, f"{node.name}() -> {type_name}")
        for type_name in sorted(returned & HELD_DATABASE_TYPES)
    ]


def _reads_session_factory_engine(node: ast.Subscript, context: _ModuleContext) -> bool:
    """Whether ``node`` is ``factory.kw["bind"]`` outside a session-factory module."""
    return (
        context.module.uses_sqlalchemy
        and not context.module.is_session_factory
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == SESSION_FACTORY_KEYWORDS
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == SESSION_FACTORY_BIND_KEY
    )


def _subscript_findings(
    node: ast.Subscript, context: _ModuleContext
) -> list[tuple[str, str]]:
    if _reads_session_factory_engine(node, context):
        return [(CORE_CONNECTION, ast.unparse(node))]
    return []


def _name_findings(node: ast.Name) -> list[tuple[str, str]]:
    """Report a read of the bare name ``__table__``, as in a class body."""
    if node.id == MAPPED_TABLE_ATTRIBUTE and isinstance(node.ctx, ast.Load):
        return [(CORE_TABLE_ACCESS, node.id)]
    return []


def _node_findings(node: ast.AST, context: _ModuleContext) -> list[tuple[str, str]]:
    findings: Iterable[tuple[str, str]] = ()
    match node:
        case ast.Import() | ast.ImportFrom():
            findings = _import_findings(node, context)
        case ast.Name():
            findings = _name_findings(node)
        case ast.Attribute():
            findings = _attribute_findings(node, context)
        case ast.Call():
            findings = _call_findings(node, context)
        case ast.FunctionDef() | ast.AsyncFunctionDef():
            findings = _function_findings(node, context)
        case ast.arg():
            findings = _table_annotation_findings(
                f"{node.arg}: ", node.annotation, context
            )
        case ast.AnnAssign():
            findings = _annotated_assignment_findings(node, context)
        case ast.Subscript():
            findings = _subscript_findings(node, context)
    return list(findings)


def _module_context(module: _Module) -> _ModuleContext:
    return _ModuleContext(
        module=module,
        metadata_names=_bound_to_calls(module, frozenset({METADATA_CONSTRUCTOR})),
        mapper_names=_bound_to_calls(module, MAPPER_FUNCTIONS)
        | _bound_to_mappers(module),
        engine_names=_bound_to_calls(module, ENGINE_FACTORIES)
        | _annotated_as(module, ENGINE_TYPES),
        schema_details=_schema_detail_calls(module.tree, module.imported),
        called={
            id(node.func)
            for node in ast.walk(module.tree)
            if isinstance(node, ast.Call)
        },
        mapped_table_annotations=_mapped_table_annotations(module),
    )


def _enclosing_scopes(tree: ast.Module) -> dict[int, str]:
    """Map each node in a class's or function's body to that scope's dotted name.

    The innermost class or function counts, its name joined to the names of
    the classes and functions around it: ``Reconciler.apply.build``. A lambda
    counts as the function it is in, and two definitions with one name in one
    scope, such as a property's getter and setter, share that name. A
    definition's own decorators, parameters and annotations belong to the
    scope around it.
    """
    scopes: dict[int, str] = {}
    pending: list[tuple[ast.AST, str | None]] = [(tree, None)]
    while pending:
        node, scope = pending.pop()
        if scope is not None:
            scopes[id(node)] = scope
        if not isinstance(node, SCOPE_NODES):
            pending.extend((child, scope) for child in ast.iter_child_nodes(node))
            continue
        inner = node.name if scope is None else f"{scope}.{node.name}"
        body = {id(statement) for statement in node.body}
        pending.extend(
            (child, inner if id(child) in body else scope)
            for child in ast.iter_child_nodes(node)
        )
    return scopes


def orm_access_findings(sources: Mapping[str, str]) -> list[Finding]:
    """Return every place the sources reach the database without the ORM.

    ``sources`` maps a repository-relative file name to its source.
    """
    findings: list[Finding] = []
    for file, source in sorted(sources.items()):
        tree = ast.parse(source, filename=file)
        module = _Module(
            file=file,
            tree=tree,
            imported=_orm_library_imports(tree),
            driver_imported=_library_imports(tree, DATABASE_DRIVER_MODULES),
        )
        context = _module_context(module)
        scopes = _enclosing_scopes(tree)
        findings.extend(
            Finding(
                file,
                getattr(node, "lineno", 0),
                check,
                finding_source,
                function=scopes.get(id(node)),
            )
            for node in ast.walk(tree)
            for check, finding_source in _node_findings(node, context)
        )
    return sorted(findings, key=lambda finding: (finding.file, finding.line))


def _relative_file(path: str | None, repository_root: Path) -> str:
    if path is None:
        return "<unknown>"
    return Path(path).resolve().relative_to(repository_root).as_posix()


def unmapped_table_findings(
    modules: Iterable[ModuleType], repository_root: Path, *, location: str | None = None
) -> list[Finding]:
    """Return each table the modules hold that no mapped class maps.

    A module holds a table through a global bound to the table, to a MetaData,
    or to a declarative base or mapped class, SQLModel classes included. Each
    table is reported once, at ``location`` when given, otherwise at the first
    module that holds it.
    """
    return _unmapped_findings(
        (module, location or _relative_file(module.__file__, repository_root))
        for module in modules
    )


def _declared_registry(value: object) -> registry | None:
    """Return the ORM registry of a declarative base or mapped class code defines.

    SQLModel classes share SQLModel's registry. The libraries' own base classes
    are not the code's, so they count only through the code's subclasses.
    """
    from sqlalchemy.orm import DeclarativeBase, DeclarativeBaseNoMeta
    from sqlmodel import SQLModel

    if not isinstance(value, type) or _orm_library(value.__module__) is not None:
        return None
    if issubclass(value, (DeclarativeBase, DeclarativeBaseNoMeta)):
        return value.registry
    if issubclass(value, SQLModel):
        return value._sa_registry
    return None


def _unmapped_findings(
    placed_modules: Iterable[tuple[ModuleType, str]],
) -> list[Finding]:
    """Report each held table no mapped class of any of the modules maps."""
    from sqlalchemy import MetaData, Table

    # Each held table's full name and where it is reported, by the table's id.
    held: dict[int, tuple[str, str]] = {}
    mapped: set[int] = set()
    for module, place in placed_modules:
        for value in vars(module).values():
            class_registry = _declared_registry(value)
            if isinstance(value, Table):
                tables = [value]
            elif isinstance(value, MetaData):
                tables = list(value.tables.values())
            elif class_registry is not None:
                mapped.update(
                    id(mapper.local_table) for mapper in class_registry.mappers
                )
                tables = list(class_registry.metadata.tables.values())
            else:
                tables = []
            for table in tables:
                held.setdefault(id(table), (table.fullname, place))
    findings = [
        Finding(place, 0, UNMAPPED_TABLE, table_name)
        for key, (table_name, place) in held.items()
        if key not in mapped
    ]
    return sorted(findings, key=lambda finding: (finding.file, finding.source))


def _package_modules(package_name: str) -> list[ModuleType]:
    package = importlib.import_module(package_name)
    names = sorted(
        module.name
        for module in pkgutil.walk_packages(package.__path__, f"{package_name}.")
    )
    return [package, *(importlib.import_module(name) for name in names)]


def unmapped_tables_in_packages(
    package_names: Iterable[str], repository_root: Path
) -> list[Finding]:
    """Import the packages and return each table they hold that no class maps.

    A table is reported once, at the source directory of the first package
    that holds it, in the order given.
    """
    placed_modules: list[tuple[ModuleType, str]] = []
    for package_name in package_names:
        package_modules = _package_modules(package_name)
        directory = PurePosixPath(
            _relative_file(package_modules[0].__file__, repository_root)
        ).parent
        placed_modules.extend((module, str(directory)) for module in package_modules)
    return _unmapped_findings(placed_modules)


def _names_finding(exception: RuleException, finding: Finding) -> bool:
    """Whether a no-orm-form exception allows ``finding``.

    Its ``path`` is the finding's file and its ``match`` the finding's
    ``source``, exactly. With a ``function``, the finding is in that function
    too, or at module level for ``MODULE_LEVEL``; without one, the exception
    allows the source anywhere in the file.
    """
    return (
        exception.category == NO_ORM_FORM
        and exception.match is not None
        and (exception.path, exception.match) == (finding.file, finding.source)
        and exception.function in (None, finding.function or MODULE_LEVEL)
    )


def undeclared_findings(
    findings: Iterable[Finding], exceptions: Iterable[RuleException]
) -> list[Finding]:
    """Return the findings that no no-orm-form exception names."""
    exceptions = list(exceptions)
    return [
        finding
        for finding in findings
        if not any(_names_finding(exception, finding) for exception in exceptions)
    ]


def unused_exceptions(
    findings: Iterable[Finding], exceptions: Iterable[RuleException]
) -> list[RuleException]:
    """Return each no-orm-form exception that names no finding."""
    findings = list(findings)
    return [
        exception
        for exception in exceptions
        if exception.category == NO_ORM_FORM
        and not any(_names_finding(exception, finding) for finding in findings)
    ]


def unscanned_files(
    exceptions: Iterable[RuleException], repository_root: Path
) -> frozenset[str]:
    """Return the files the migration-revision exceptions' path patterns name."""
    return frozenset(
        path.relative_to(repository_root).as_posix()
        for exception in exceptions
        if exception.category == MIGRATION_REVISION
        for path in repository_root.glob(exception.path)
        if path.is_file()
    )


def _literal_text(argument: ast.expr) -> str | None:
    """Return a string argument's text, an f-string's with each value a space.

    Return ``None`` for any other argument.
    """
    if isinstance(argument, ast.Constant):
        return argument.value if isinstance(argument.value, str) else None
    if not isinstance(argument, ast.JoinedStr):
        return None
    return "".join(
        part.value
        if isinstance(part, ast.Constant) and isinstance(part.value, str)
        else " "
        for part in argument.values
    )


def _holds_literal_sql(argument: ast.expr) -> bool:
    """Whether a string or f-string argument names a SQL statement of its own.

    Its literal text, less its SQL comments, holds a statement keyword as a
    whole word: ``'TRUNCATE reports'`` and ``f'TRUNCATE {tables}'`` do;
    ``f'{statement};'``, ``f'{schema}.{table}'``, ``'-- SELECT 1'`` and
    ``'count(*)'`` don't.
    """
    literal = _literal_text(argument)
    if literal is None:
        return False
    return bool(SQL_STATEMENT_KEYWORD.search(SQL_COMMENT.sub(" ", literal)))


def _names_sql_text(match: str) -> bool:
    """Whether ``match`` is raw SQL, or a statement method, given SQL of its own.

    Such a match names one statement: a raw SQL construct (``text``,
    ``TextClause``, ``literal_column``, ``DDL``) or a statement method
    (``execute``, ``exec_driver_sql``, ``scalar`` and the like) whose first
    argument holds a statement keyword outside its comments, as
    ``text(f'TRUNCATE {tables}')`` does. A string given to anything else, such
    as ``sqlite3.connect(':memory:')``, an expression such as
    ``literal_column('count(*)')``, a bare call, a call on variables and an
    attribute read name none.
    """
    try:
        expression = ast.parse(match, mode="eval").body
    except SyntaxError:
        return False
    return (
        isinstance(expression, ast.Call)
        and bool(expression.args)
        and _last_name(expression.func) in SQL_TEXT_CALLS
        and _holds_literal_sql(expression.args[0])
    )


def _needs_function(exception: RuleException, match: str) -> bool:
    """Whether a no-orm-form exception must name the function it allows.

    Every exception outside the tests does, and so does one whose match names
    no statement, which would otherwise allow every such call in its module.
    """
    return exception.function is None and (
        not exception.path.startswith(TEST_DIRECTORY) or not _names_sql_text(match)
    )


def _construct_exception_problem(
    exception: RuleException, repository_root: Path
) -> str | None:
    """Describe what makes a no-orm-form exception unusable, or return ``None``."""
    where = f"exception for {exception.path}"
    if exception.match is None:
        return f"{where} names no construct: set match to the finding's source"
    if not (repository_root / exception.path).is_file():
        return f"{where} must name one existing file"
    if _needs_function(exception, exception.match):
        return (
            f"{where} ({exception.match}) needs a function: set function to the "
            f"enclosing function of its finding, or to {MODULE_LEVEL} for a "
            "finding at module level"
        )
    return None


def _path_exception_problem(
    exception: RuleException, read_files: frozenset[str], repository_root: Path
) -> str | None:
    """Describe what makes a migration-revision exception unusable, or ``None``."""
    where = f"exception for {exception.path}"
    if exception.match is not None:
        return f"{where} skips whole files, so it takes no match"
    if exception.function is not None:
        return f"{where} skips whole files, so it takes no function"
    if not unscanned_files([exception], repository_root) & read_files:
        return f"{where} matches no file the rule test reads: remove it"
    return None


def _exception_problem(
    exception: RuleException, read_files: frozenset[str], repository_root: Path
) -> str | None:
    """Describe what makes one exception unusable, or return ``None``."""
    if exception.category == NO_ORM_FORM:
        return _construct_exception_problem(exception, repository_root)
    if exception.category == MIGRATION_REVISION:
        return _path_exception_problem(exception, read_files, repository_root)
    return (
        f"exception for {exception.path} has unknown category "
        f"{exception.category!r}: use one of {list(EXCEPTION_CATEGORIES)}"
    )


def exception_problems(
    exceptions: Iterable[RuleException],
    read_files: Iterable[str],
    repository_root: Path,
) -> list[str]:
    """Describe each exception with an unknown category, module, construct or function.

    ``read_files`` are the repository-relative files the rule test reads before
    the migration-revision exceptions take theirs out.
    """
    read = frozenset(read_files)
    return [
        problem
        for exception in exceptions
        if (problem := _exception_problem(exception, read, repository_root))
    ]
