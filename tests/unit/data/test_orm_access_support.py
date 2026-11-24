"""Unit tests for the checks behind rule api.data.orm-only.

Ported from policyengine-sim-api's tests of the checker behind
sim.persistence.orm-only, with tests added for this repository's changes:
SQLModel's names, the named session-factory and declarative-base modules, event
listeners, and the rule's exceptions.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from textwrap import dedent

import pytest

from scripts.rules.model import RuleException
from tests.unit.data.orm_access_support import (
    CORE_CONNECTION,
    CORE_TABLE_ACCESS,
    CORE_TABLE_DECLARATION,
    DECLARATIVE_BASE_MODULES,
    MIGRATION_REVISION,
    NO_ORM_FORM,
    RAW_SQL,
    SESSION_FACTORY_MODULES,
    UNMAPPED_TABLE,
    Finding,
    exception_problems,
    orm_access_findings,
    undeclared_findings,
    unmapped_table_findings,
    unscanned_files,
    unused_exceptions,
)

STORE = "policyengine_api/data/v2/example_store.py"
SESSION_FACTORY = "policyengine_api/data/v2/database.py"
DECLARATIVE_BASE = "policyengine_api/data/v1_models.py"
ROUTES = "policyengine_api/routes/example_routes.py"
MODELS = "policyengine_api/data/v2/example_models.py"


def _checks(sources: dict[str, str], file: str) -> list[tuple[str, str]]:
    """Return the (check, source) findings in ``file``."""
    findings = orm_access_findings(
        {name: dedent(source) for name, source in sources.items()}
    )
    return [
        (finding.check, finding.source) for finding in findings if finding.file == file
    ]


@pytest.mark.parametrize(
    "statement",
    [
        "select(func.count().label('jobs'))",
        "select(cast(HouseholdJob.year, String).label('year'))",
        "select(exists().where(HouseholdJob.id == job_id))",
        "select(*columns)",
        "select(pending.c.id).where(pending.c.id == job_id)",
        "select(func.count()).select_from(HouseholdJob).join(Policy)",
        "insert(HouseholdJob).values(id=job_id).on_conflict_do_nothing()",
        "select(reports.c.id)",
    ],
)
def test_orm_statements_are_accepted(statement: str) -> None:
    store = f"""
    from sqlalchemy import String, cast, exists, func, insert, select

    pending = select(HouseholdJob.id).subquery()
    reports = select(Report.id).where(Report.year == 2026).subquery()
    statement = {statement}
    """

    assert _checks({STORE: store}, STORE) == []


@pytest.mark.parametrize(
    ("declaration", "summary"),
    [
        ("def read(jobs: Table): ...", "jobs: Table"),
        ("def read(jobs: TableClause): ...", "jobs: TableClause"),
        ("def read(jobs: 'sa.Table | None'): ...", "jobs: sa.Table | None"),
        ("def read(*tables: Table): ...", "tables: Table"),
        ("def read(**tables: Table): ...", "tables: Table"),
        ("def read() -> Table: ...", "read() -> Table"),
        ("async def read() -> list[Table]: ...", "read() -> list[Table]"),
        ("selected: Table = choose()", "selected: Table"),
        ("self.jobs: Table = source", "self.jobs: Table"),
        ("class Rows:\n    target: Table", "target: Table"),
        (
            "def read(jobs: Annotated[Any, Marker(kind=Table)]): ...",
            "jobs: Annotated[Any, Marker(kind=Table)]",
        ),
        ("def read(jobs: Literal[Table]): ...", "jobs: Literal[Table]"),
    ],
)
def test_an_annotation_naming_a_core_table_type_is_reported(
    declaration: str, summary: str
) -> None:
    store = f"""
import sqlalchemy as sa
from sqlalchemy import Table, TableClause

{declaration}
"""

    assert _checks({STORE: store}, STORE) == [(CORE_TABLE_ACCESS, summary)]


@pytest.mark.parametrize(
    "annotation",
    [
        'Literal["Table"]',
        'Choice["Table", "View"]',
        'Annotated[str, "Table"]',
        'Annotated[str, "' + "x." * 1000 + 'y"]',
        'Optional["Table"]',
        "\"list['Table']\"",
        '"not a type ("',
    ],
)
def test_a_quoted_name_inside_an_annotation_is_not_read(annotation: str) -> None:
    """Only a wholly quoted annotation is parsed; other strings may be anything."""
    store = f"""
from sqlalchemy import Table

def read(value: {annotation}): ...
"""

    assert _checks({STORE: store}, STORE) == []


def test_an_engine_type_in_annotation_metadata_is_followed() -> None:
    source = """
    from sqlalchemy import Engine

    def hand_out() -> Annotated[Any, Marker(kind=Engine)]: ...

    def run(handle: Annotated[Any, Marker(kind=Engine)]):
        return handle.begin()
    """

    assert _checks({SESSION_FACTORY: source}, SESSION_FACTORY) == [
        (CORE_CONNECTION, "hand_out() -> Engine"),
    ]
    assert _checks({STORE: source}, STORE) == [
        (CORE_CONNECTION, "sqlalchemy.Engine"),
        (CORE_CONNECTION, "handle.begin()"),
    ]


def test_a_declarative_base_module_may_annotate_a_mapped_classs_table() -> None:
    source = """
    from typing import ClassVar

    from sqlalchemy import Table

    class TableModel:
        __table__: ClassVar[Table]
    """

    assert _checks({DECLARATIVE_BASE: source}, DECLARATIVE_BASE) == []
    assert _checks({STORE: source}, STORE) == [
        (CORE_TABLE_ACCESS, "__table__: ClassVar[Table]")
    ]


@pytest.mark.parametrize(
    ("declaration", "summary"),
    [
        ("def read(jobs: Table): ...", "jobs: Table"),
        ("selected: Table = choose()", "selected: Table"),
        ("class Rows:\n    target: Table", "target: Table"),
        ("def read(__table__: Table): ...", "__table__: Table"),
        ("__table__: Table = choose()", "__table__: Table"),
        (
            "class Rows:\n    def read(self):\n        __table__: Table = choose()",
            "__table__: Table",
        ),
    ],
)
def test_a_declarative_base_module_annotates_only_table_of_its_classes(
    declaration: str, summary: str
) -> None:
    source = f"from sqlalchemy import Table\n\n{declaration}\n"

    assert _checks({DECLARATIVE_BASE: source}, DECLARATIVE_BASE) == [
        (CORE_TABLE_ACCESS, summary)
    ]


@pytest.mark.parametrize(
    "guarded_class_body",
    [
        "if TYPE_CHECKING:\n        __table__: ClassVar[Table]",
        "if RUNTIME:\n        pass\n    else:\n        __table__: ClassVar[Table]",
        (
            "if RUNTIME:\n        pass\n    elif TYPE_CHECKING:\n"
            "        __table__: ClassVar[Table]"
        ),
    ],
)
def test_a_guarded_table_annotation_in_a_class_is_accepted(
    guarded_class_body: str,
) -> None:
    source = f"""
from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import Table

class TableModel:
    {guarded_class_body}
"""

    assert _checks({DECLARATIVE_BASE: source}, DECLARATIVE_BASE) == []


@pytest.mark.parametrize("file", [DECLARATIVE_BASE, STORE])
def test_reading_a_bare_mapped_table_name_is_core_table_access(file: str) -> None:
    source = """
    from typing import ClassVar

    from sqlalchemy import select

    class JobRecord:
        __table__ = build_jobs_table()
        pending = select(__table__)
    """

    assert _checks({file: source}, file) == [(CORE_TABLE_ACCESS, "__table__")]


def test_a_declarative_base_module_may_not_declare_a_core_table() -> None:
    source = """
    from sqlalchemy import Table

    jobs = Table("household_jobs", metadata)
    """

    assert _checks({DECLARATIVE_BASE: source}, DECLARATIVE_BASE) == [
        (CORE_TABLE_DECLARATION, "Table('household_jobs', ...)")
    ]


@pytest.mark.parametrize(
    "table_expression",
    [
        "HouseholdJob.__table__",
        "inspect(HouseholdJob).local_table",
        "inspect(HouseholdJob).persist_selectable",
        "Base.metadata.sorted_tables",
    ],
)
def test_a_table_is_reported_where_it_is_reached_and_not_where_it_is_used(
    table_expression: str,
) -> None:
    models = f"""
    from policyengine_api.data.v2.models import Base, HouseholdJob
    from sqlalchemy import inspect, select

    jobs = {table_expression}
    statement = select(jobs)
    """
    store = """
    from policyengine_api.data.v2.example_models import jobs
    from sqlalchemy import select

    statement = select(jobs)
    """
    sources = {MODELS: models, STORE: store}

    assert _checks(sources, MODELS) == [(CORE_TABLE_ACCESS, table_expression)]
    assert _checks(sources, STORE) == []


def test_a_table_declared_in_another_module_is_reported_where_it_is_declared() -> None:
    tables = """
    from sqlalchemy import MetaData, Table

    metadata = MetaData()
    household_jobs = Table("household_jobs", metadata)
    """
    store = """
    from policyengine_api.data.v2.example_tables import household_jobs
    from sqlalchemy import select

    statement = select(household_jobs)
    """
    tables_module = "policyengine_api/data/v2/example_tables.py"
    sources = {tables_module: tables, STORE: store}

    assert _checks(sources, tables_module) == [
        (CORE_TABLE_DECLARATION, "MetaData()"),
        (CORE_TABLE_DECLARATION, "Table('household_jobs', ...)"),
    ]
    assert _checks(sources, STORE) == []


def test_two_files_may_share_a_module_name() -> None:
    sources = {
        "policyengine_api/services/v2/reports/database_session.py": "",
        "policyengine_api/services/v2/policies/database_session.py": "",
    }

    assert orm_access_findings(sources) == []


def test_a_bare_mapped_table_read_is_reported_without_a_sqlalchemy_import() -> None:
    source = """
    class JobRecord:
        __table__ = build_jobs_table()
        pending = __table__.select()
    """

    assert _checks({STORE: source}, STORE) == [(CORE_TABLE_ACCESS, "__table__")]


def test_names_shared_with_core_tables_elsewhere_are_not_core_tables() -> None:
    routes = """
    import pyarrow as pa

    def describe(regions: list[str], households, frame: pa.Table) -> str:
        return ", ".join(regions) + str(households.columns) + str(frame.columns)
    """

    assert _checks({ROUTES: routes}, ROUTES) == []


def test_sql_text_is_accepted_as_a_server_default_or_index_condition() -> None:
    store = """
    from sqlalchemy import CheckConstraint, Index, text
    from sqlalchemy.orm import mapped_column

    created_at = mapped_column(server_default=text("now()"))
    positive = CheckConstraint(text("key_version > 0"), name="ck_key_version")
    index = Index("ix_pending", "status", postgresql_where=text("status = 'pending'"))
    """

    assert _checks({STORE: store}, STORE) == []


def test_names_from_other_packages_are_not_sqlalchemy() -> None:
    store = """
    from textwrap import dedent as text

    settings.update(region="uk")
    text("SELECT 1")
    """

    assert _checks({STORE: store}, STORE) == []


def test_metadata_is_accepted_only_in_a_declarative_base_module() -> None:
    source = """
    from sqlalchemy import MetaData

    metadata = MetaData(schema="public")
    """

    assert _checks({DECLARATIVE_BASE: source}, DECLARATIVE_BASE) == []
    assert _checks({STORE: source}, STORE) == [
        (CORE_TABLE_DECLARATION, "MetaData(...)")
    ]


@pytest.mark.parametrize("file", sorted(DECLARATIVE_BASE_MODULES))
def test_every_declarative_base_module_may_build_metadata(file: str) -> None:
    source = "from sqlalchemy import MetaData\n\nmetadata = MetaData()\n"

    assert _checks({file: source}, file) == []


def test_lightweight_tables_and_columns_are_core_declarations() -> None:
    store = """
    import sqlalchemy as sa

    pg_class = sa.table("pg_class", sa.column("relname"))
    """

    assert _checks({STORE: store}, STORE) == [
        (CORE_TABLE_DECLARATION, "sa.table('pg_class', ...)"),
        (CORE_TABLE_DECLARATION, "sa.column('relname')"),
    ]


@pytest.mark.parametrize(
    "expression",
    [
        "Base.metadata.tables['household_jobs']",
        "schema.tables['household_jobs']",
        "schema.sorted_tables",
        "HouseholdJob.__mapper__.local_table",
        "HouseholdJob.__mapper__.tables",
        "inspect(HouseholdJob).persist_selectable",
        "inspect(HouseholdJob).selectable",
        "HouseholdJob.__table__",
        "class_mapper(HouseholdJob).tables",
        "inspect(HouseholdJob).mapper.tables",
        "job_mapper.tables",
        "held_mapper.tables",
        "inspected_mapper.tables",
        "HouseholdJob.id.table",
    ],
)
def test_reaching_a_mapped_class_or_metadata_table_is_core_table_access(
    expression: str,
) -> None:
    store = f"""
    from sqlalchemy import MetaData, inspect
    from sqlalchemy.orm import class_mapper

    schema = MetaData()
    job_mapper = inspect(HouseholdJob)
    held_mapper = HouseholdJob.__mapper__
    inspected_mapper = inspect(job).mapper
    table = {expression}
    """

    assert [
        check
        for check, _ in _checks({STORE: store}, STORE)
        if check != CORE_TABLE_DECLARATION
    ] == [CORE_TABLE_ACCESS]


def test_engines_are_held_only_by_a_session_factory_module() -> None:
    source = """
    from sqlalchemy import Engine, create_engine
    from sqlalchemy.orm import sessionmaker
    """

    assert _checks({SESSION_FACTORY: source}, SESSION_FACTORY) == []
    assert _checks({STORE: source}, STORE) == [
        (CORE_CONNECTION, "sqlalchemy.Engine"),
        (CORE_CONNECTION, "sqlalchemy.create_engine"),
    ]


@pytest.mark.parametrize("file", sorted(SESSION_FACTORY_MODULES))
def test_every_session_factory_module_may_build_an_engine_and_connect(
    file: str,
) -> None:
    source = """
    from sqlalchemy import create_engine, event
    from sqlalchemy.engine import Connection

    def _connect_sessions(url):
        engine = create_engine(url)
        event.listen(engine, "connect", _on_connect)
        connection: Connection = engine.connect()
        return connection
    """

    assert _checks({file: source}, file) == []


def test_a_session_factory_module_may_open_connections_other_modules_may_not() -> None:
    source = """
    from sqlalchemy import Engine
    from sqlalchemy.engine import Connection

    def bounded_transaction(engine: Engine):
        with engine.begin() as connection:
            yield connection

    def store_transaction(store):
        return store._engine.begin()

    def session_transaction(session_factory):
        return session_factory.begin()
    """

    assert _checks({SESSION_FACTORY: source}, SESSION_FACTORY) == []
    assert _checks({STORE: source}, STORE) == [
        (CORE_CONNECTION, "sqlalchemy.Engine"),
        (CORE_CONNECTION, "sqlalchemy.engine.Connection"),
        (CORE_CONNECTION, "engine.begin()"),
        (CORE_CONNECTION, "store._engine.begin()"),
    ]


@pytest.mark.parametrize(
    "call",
    ["engine.connect()", "session.connection()", "session.get_bind()"],
)
def test_opening_a_connection_is_reported_outside_a_session_factory_module(
    call: str,
) -> None:
    source = f"import sqlalchemy\n\nvalue = {call}"

    assert _checks({STORE: source}, STORE) == [(CORE_CONNECTION, call)]
    assert _checks({SESSION_FACTORY: source}, SESSION_FACTORY) == []


def test_a_driver_connection_is_reported_in_every_module() -> None:
    source = "import sqlalchemy\n\nvalue = engine.raw_connection()"

    for file in (STORE, SESSION_FACTORY):
        assert _checks({file: source}, file) == [
            (CORE_CONNECTION, "engine.raw_connection()")
        ]


@pytest.mark.parametrize(
    ("call", "summary"),
    [
        ("connection.execute(statement)", "connection.execute(...)"),
        ("conn.scalar(statement)", "conn.scalar(...)"),
        ("store_connection.scalars(statement)", "store_connection.scalars(...)"),
        ("self._connection.execute(statement)", "self._connection.execute(...)"),
        ("connection.stream(statement)", "connection.stream(...)"),
        ("connection.stream_scalars(statement)", "connection.stream_scalars(...)"),
        ("bind.execute(statement)", "bind.execute(...)"),
        ("database.execute(statement)", "database.execute(...)"),
        ("self.store.execute(statement)", "self.store.execute(...)"),
        ("connections.execute(statement)", "connections.execute(...)"),
    ],
)
def test_a_statement_on_an_unannotated_connection_is_reported(
    call: str, summary: str
) -> None:
    """``execute`` must run on a session, whatever else its receiver is called."""
    source = f"import sqlalchemy\n\nvalue = {call}"

    for file in (STORE, SESSION_FACTORY):
        assert _checks({file: source}, file) == [(CORE_CONNECTION, summary)]


@pytest.mark.parametrize(
    "call",
    [
        "session.execute(statement)",
        "session.scalar(statement)",
        "session.scalars(statement)",
        "self._session.execute(statement)",
        "store_session.execute(statement)",
        "Session(bind).execute(statement)",
        "session.execute(statement).scalars()",
        "result.scalars()",
        "result.scalar()",
    ],
)
def test_a_statement_on_a_session_is_not_reported(call: str) -> None:
    source = f"import sqlalchemy\n\nvalue = {call}"

    assert _checks({STORE: source}, STORE) == []


@pytest.mark.parametrize(
    ("call", "summary"),
    [
        (
            "sqlite_connection.execute('PRAGMA foreign_keys = ON')",
            "sqlite_connection.execute('PRAGMA foreign_keys = ON')",
        ),
        (
            "connection.execute('SELECT 1', parameters)",
            "connection.execute('SELECT 1', ...)",
        ),
        ("conn.scalar('SELECT 1')", "conn.scalar('SELECT 1')"),
        ("connection.execute(statement, parameters)", "connection.execute(...)"),
        ("connection.execute(statement, timeout=5)", "connection.execute(...)"),
    ],
)
def test_a_statement_outside_a_session_reports_its_constant_arguments(
    call: str, summary: str
) -> None:
    """A constant statement is reported, so an exception can name that statement."""
    source = f"import sqlalchemy\n\nvalue = {call}"

    assert _checks({STORE: source}, STORE) == [(CORE_CONNECTION, summary)]


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


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (
            "session.connection().exec_driver_sql('DELETE FROM reports')",
            [
                (
                    RAW_SQL,
                    "session.connection().exec_driver_sql('DELETE FROM reports')",
                ),
                (CORE_CONNECTION, "session.connection()"),
            ],
        ),
        ("session.get_bind()", [(CORE_CONNECTION, "session.get_bind()")]),
        ("engine.raw_connection()", [(CORE_CONNECTION, "engine.raw_connection()")]),
        (
            "database.exec_driver_sql('SELECT 1')",
            [(RAW_SQL, "database.exec_driver_sql('SELECT 1')")],
        ),
    ],
)
def test_connections_and_driver_sql_are_reported_without_a_sqlalchemy_import(
    call: str, expected: list[tuple[str, str]]
) -> None:
    """These method names mean SQLAlchemy whatever the module imports."""
    assert _checks({ROUTES: f"value = {call}"}, ROUTES) == expected


@pytest.mark.parametrize(
    "call",
    [
        "connection.execute(statement)",
        "connection.scalars(statement)",
        "socket.connect()",
        "connect(url)",
        "driver.cursor()",
        "cache_engine.begin()",
    ],
)
def test_ambiguous_method_names_are_not_reported_outside_sqlalchemy(call: str) -> None:
    """Other libraries share these names, so they count only beside sqlalchemy."""
    assert _checks({ROUTES: f"value = {call}"}, ROUTES) == []


@pytest.mark.parametrize(
    ("imports", "call", "summary"),
    [
        ("import psycopg", "psycopg.connect(url)", "psycopg.connect(url)"),
        ("import psycopg2", "psycopg2.connect(url)", "psycopg2.connect(url)"),
        ("import pymysql", "pymysql.connect(host='localhost')", "pymysql.connect(...)"),
        (
            "import sqlite3",
            "sqlite3.connect(':memory:')",
            "sqlite3.connect(':memory:')",
        ),
        (
            "import mysql.connector",
            "mysql.connector.connect(user='root')",
            "mysql.connector.connect(...)",
        ),
        ("import psycopg as pg", "pg.connect(url)", "pg.connect(url)"),
        ("from psycopg import connect", "connect(url)", "connect(url)"),
        (
            "from mysql import connector",
            "connector.connect(user='root')",
            "connector.connect(...)",
        ),
    ],
)
def test_a_database_drivers_connect_is_reported_outside_a_session_factory_module(
    imports: str, call: str, summary: str
) -> None:
    source = f"{imports}\n\ndriver_connection = {call}\n"

    assert _checks({ROUTES: source}, ROUTES) == [(CORE_CONNECTION, summary)]
    assert _checks({SESSION_FACTORY: source}, SESSION_FACTORY) == []


def test_a_statement_on_a_driver_connection_is_reported_where_it_connects() -> None:
    source = "import psycopg\n\npsycopg.connect(url).execute('DELETE FROM reports')\n"

    assert _checks({ROUTES: source}, ROUTES) == [
        (CORE_CONNECTION, "psycopg.connect(url)")
    ]


def test_a_session_factory_module_hands_out_no_engine_or_connection() -> None:
    source = """
    from sqlalchemy import Connection, Engine, create_engine
    from sqlalchemy.orm import Session, sessionmaker

    def _private_engine(url) -> Engine:
        return create_engine(url)

    def public_engine(url) -> Engine:
        return create_engine(url)

    def optional_engine(url) -> "Engine | None":
        return None

    def public_connection(engine) -> Connection:
        return engine.connect()

    def session_factory(engine: Engine) -> sessionmaker[Session]:
        return sessionmaker(engine)

    class Sessions:
        def engine(self) -> Engine:
            return self._engine
    """

    assert _checks({SESSION_FACTORY: source}, SESSION_FACTORY) == [
        (CORE_CONNECTION, "public_engine() -> Engine"),
        (CORE_CONNECTION, "optional_engine() -> Engine"),
        (CORE_CONNECTION, "public_connection() -> Connection"),
        (CORE_CONNECTION, "engine() -> Engine"),
    ]


def test_only_a_session_factory_module_reads_a_session_factorys_engine() -> None:
    source = """
    import sqlalchemy

    engine = session_factory.kw["bind"]
    autoflush = session_factory.kw["autoflush"]
    """

    assert _checks({SESSION_FACTORY: source}, SESSION_FACTORY) == []
    assert _checks({STORE: source}, STORE) == [
        (CORE_CONNECTION, "session_factory.kw['bind']"),
    ]


@pytest.mark.parametrize(
    ("source", "summary"),
    [
        ("sa.text('SELECT 1')", "sa.text('SELECT 1')"),
        ("sa.literal_column('count(*)')", "sa.literal_column('count(*)')"),
        ("session.exec_driver_sql('SELECT 1')", "session.exec_driver_sql('SELECT 1')"),
        ("driver_connection.cursor()", "driver_connection.cursor()"),
        ("sa.DDL('DROP TABLE reports')", "sa.DDL('DROP TABLE reports')"),
        (
            "sa.schema.DDL('ALTER TABLE reports ADD note text')",
            "sa.schema.DDL('ALTER TABLE reports ADD note text')",
        ),
        ("DDL('DROP TABLE reports')", "DDL('DROP TABLE reports')"),
    ],
)
def test_raw_sql_is_reported(source: str, summary: str) -> None:
    store = f"""
    import sqlalchemy as sa
    from sqlalchemy.schema import DDL

    statement = {source}
    """

    for file in (STORE, SESSION_FACTORY):
        assert _checks({file: store}, file) == [(RAW_SQL, summary)]


@pytest.mark.parametrize(
    "statement",
    [
        "from sqlmodel import Field, Session, SQLModel, col, select",
        "import sqlmodel",
        "from sqlmodel.sql.sqltypes import AutoString",
    ],
)
def test_sqlmodel_imports_are_accepted(statement: str) -> None:
    assert _checks({STORE: statement}, STORE) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "from sqlmodel import text\n\nstatement = text('SELECT 1')",
            [(RAW_SQL, "text('SELECT 1')")],
        ),
        (
            "import sqlmodel\n\nstatement = sqlmodel.text('SELECT 1')",
            [(RAW_SQL, "sqlmodel.text('SELECT 1')")],
        ),
        (
            "from sqlmodel import create_engine",
            [(CORE_CONNECTION, "sqlmodel.create_engine")],
        ),
        (
            "import sqlmodel\n\nengine = sqlmodel.create_engine(url)",
            [(CORE_CONNECTION, "sqlmodel.create_engine")],
        ),
        (
            "from sqlmodel import Table\n\njobs = Table('household_jobs', metadata)",
            [(CORE_TABLE_DECLARATION, "Table('household_jobs', ...)")],
        ),
        (
            "from sqlmodel import SQLModel\n\ntables = SQLModel.metadata.tables",
            [(CORE_TABLE_ACCESS, "SQLModel.metadata.tables")],
        ),
        (
            "from sqlmodel import Session\n\nrows = connection.execute(statement)",
            [(CORE_CONNECTION, "connection.execute(...)")],
        ),
    ],
)
def test_sqlalchemy_names_imported_from_sqlmodel_are_checked(
    source: str, expected: list[tuple[str, str]]
) -> None:
    assert _checks({STORE: source}, STORE) == expected


@pytest.mark.parametrize(
    ("listener", "summary"),
    [
        (
            "event.listen(engine, 'connect', set_role)",
            "event.listen(engine, 'connect')",
        ),
        (
            "event.listen(engine.pool, 'checkout', check)",
            "event.listen(engine.pool, 'checkout')",
        ),
        (
            "event.listen(bind, 'before_cursor_execute', record, retval=True)",
            "event.listen(bind, 'before_cursor_execute')",
        ),
        (
            "event.listen(engine, 'handle_error', record_error)",
            "event.listen(engine, 'handle_error')",
        ),
        (
            "@sa.event.listens_for(engine, 'connect')\ndef on_connect(): ...",
            "sa.event.listens_for(engine, 'connect')",
        ),
        (
            "@listens_for(engine, 'begin')\ndef on_begin(): ...",
            "listens_for(engine, 'begin')",
        ),
    ],
)
def test_pool_engine_and_dialect_event_listeners_need_a_session_factory_module(
    listener: str, summary: str
) -> None:
    source = (
        "import sqlalchemy as sa\nfrom sqlalchemy import event\n"
        f"from sqlalchemy.event import listens_for\n\n{listener}\n"
    )

    assert _checks({STORE: source}, STORE) == [(CORE_CONNECTION, summary)]
    assert _checks({SESSION_FACTORY: source}, SESSION_FACTORY) == []


@pytest.mark.parametrize(
    "listener",
    [
        "event.listen(factory, 'before_flush', refuse_flush)",
        "event.listen(Session, 'after_commit', record)",
        "event.listen(HouseholdJob, 'before_insert', stamp)",
        "event.listen(engine, event_name, record)",
        "signals.listen(engine, 'connect', record)",
    ],
)
def test_session_and_mapper_event_listeners_are_accepted(listener: str) -> None:
    source = f"from sqlalchemy import event\n\n{listener}\n"

    assert _checks({STORE: source}, STORE) == []


@pytest.mark.parametrize(
    ("binding", "receiver"),
    [
        ("first, label = create_engine(url), 'primary'", "first"),
        ("(first, label), other = (create_engine(url), 'a'), 1", "first"),
        ("[first, label] = [create_engine(url), 'primary']", "first"),
        ("self.first = create_engine(url)", "self.first"),
        ("first: object = create_engine(url)", "first"),
        ("value = (first := create_engine(url))", "first"),
    ],
)
def test_every_way_of_binding_an_engine_is_followed_to_begin(
    binding: str, receiver: str
) -> None:
    source = f"""
    from sqlalchemy import create_engine

    {binding}
    transaction = {receiver}.begin()
    """

    assert _checks({STORE: source}, STORE) == [
        (CORE_CONNECTION, "sqlalchemy.create_engine"),
        (CORE_CONNECTION, f"{receiver}.begin()"),
    ]


def test_a_name_annotated_as_an_engine_is_followed_to_begin() -> None:
    source = """
    from sqlalchemy import Engine

    def open_transaction(primary: "Engine | None", held: Engine):
        return primary.begin(), held.begin()
    """

    assert _checks({STORE: source}, STORE) == [
        (CORE_CONNECTION, "sqlalchemy.Engine"),
        (CORE_CONNECTION, "primary.begin()"),
        (CORE_CONNECTION, "held.begin()"),
    ]


@pytest.mark.parametrize(
    ("binding", "read"),
    [
        ("schema, label = MetaData(), 'public'", "schema.tables"),
        ("job_mapper, label = inspect(HouseholdJob), 'jobs'", "job_mapper.tables"),
        ("job_mapper, label = HouseholdJob.__mapper__, 'jobs'", "job_mapper.tables"),
    ],
)
def test_tuple_assignments_bind_metadata_and_mappers(binding: str, read: str) -> None:
    source = f"""
    from sqlalchemy import MetaData, inspect

    {binding}
    value = {read}
    """

    assert _checks({DECLARATIVE_BASE: source}, DECLARATIVE_BASE) == [
        (CORE_TABLE_ACCESS, read)
    ]


def test_begin_counts_as_opening_a_connection_only_on_an_engine() -> None:
    store = """
    from sqlalchemy import create_engine

    primary = create_engine(url)
    first = primary.begin()
    second = policyengine_settings.begin()
    """

    assert _checks({STORE: store}, STORE) == [
        (CORE_CONNECTION, "sqlalchemy.create_engine"),
        (CORE_CONNECTION, "primary.begin()"),
    ]


def test_async_engines_and_connections_are_reported() -> None:
    store = "from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine"

    assert _checks({STORE: store}, STORE) == [
        (CORE_CONNECTION, "sqlalchemy.ext.asyncio.AsyncConnection"),
        (CORE_CONNECTION, "sqlalchemy.ext.asyncio.AsyncEngine"),
    ]


@pytest.mark.parametrize(
    ("source", "check"),
    [
        ("sa.TableClause('household_jobs')", CORE_TABLE_DECLARATION),
        ("sa.ColumnClause('id')", CORE_TABLE_DECLARATION),
        ("sa.TextClause('SELECT 1')", RAW_SQL),
    ],
)
def test_core_clause_classes_are_reported(source: str, check: str) -> None:
    store = f"""
    import sqlalchemy as sa

    clause = {source}
    """

    assert [found for found, _ in _checks({STORE: store}, STORE)] == [check]


def _load_module(
    name: str, source: str, monkeypatch: pytest.MonkeyPatch
) -> types.ModuleType:
    module = types.ModuleType(name)
    # SQLAlchemy resolves a mapped class's annotations in its module.
    monkeypatch.setitem(sys.modules, name, module)
    exec(compile(dedent(source), name, "exec"), module.__dict__)  # noqa: S102  # runs the test's own module source
    return module


def test_the_runtime_check_accepts_tables_mapped_by_either_declarative_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapped = _load_module(
        "orm_only_mapped_models",
        """
        from sqlalchemy import MetaData, Table
        from sqlalchemy.orm import (
            DeclarativeBase,
            DeclarativeBaseNoMeta,
            Mapped,
            mapped_column,
        )

        class Base(DeclarativeBase):
            pass

        class NoMetaBase(DeclarativeBaseNoMeta):
            metadata = MetaData()

        class HouseholdJob(Base):
            __tablename__ = "household_jobs"
            id: Mapped[int] = mapped_column(primary_key=True)

        class Report(NoMetaBase):
            __tablename__ = "reports"
            id: Mapped[int] = mapped_column(primary_key=True)

        stray = Table("stray", Base.metadata)
        """,
        monkeypatch,
    )

    findings = unmapped_table_findings([mapped], Path(), location="example")

    assert [(finding.check, finding.source) for finding in findings] == [
        (UNMAPPED_TABLE, "stray")
    ]


def test_the_runtime_check_accepts_sqlmodel_table_classes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLModel table classes are mapped classes.

    The classes use a registry of their own, so they stay out of the v2 tables'
    metadata, which SQLModel's default registry holds.
    """
    mapped = _load_module(
        "orm_only_sqlmodel_models",
        """
        from sqlalchemy import Table
        from sqlalchemy.orm import registry
        from sqlmodel import Field, SQLModel

        class ExampleBase(SQLModel, registry=registry()):
            pass

        class HouseholdJob(ExampleBase, table=True):
            __tablename__ = "household_jobs"
            id: int | None = Field(default=None, primary_key=True)

        stray = Table("stray", ExampleBase.metadata)
        """,
        monkeypatch,
    )

    findings = unmapped_table_findings([mapped], Path(), location="example")

    assert [(finding.check, finding.source) for finding in findings] == [
        (UNMAPPED_TABLE, "stray")
    ]


@pytest.mark.parametrize(
    "expression", ["key.table", "job_id.table", "self.model.id.table", "rows.table"]
)
def test_any_table_read_in_a_module_using_sqlalchemy_is_core_table_access(
    expression: str,
) -> None:
    store = f"""
    from sqlalchemy import insert

    def write(self, key, job_id, rows):
        return insert({expression})
    """

    assert _checks({STORE: store}, STORE) == [(CORE_TABLE_ACCESS, expression)]


def test_a_called_or_assigned_table_attribute_is_not_a_table_read() -> None:
    store = """
    import sqlalchemy as sa

    class Report:
        def __init__(self, rows, model):
            self.table = model
            self.rows = rows.table(columns=["id"])
    """

    assert _checks({STORE: store}, STORE) == []


def test_name_rules_apply_only_in_modules_that_use_sqlalchemy() -> None:
    routes = """
    def publish(settings, socket, cache_engine, driver):
        settings.bigquery.table
        socket.connect()
        cache_engine.begin()
        driver.cursor()
        event.listen(cache_engine, "connect", record)
    """

    assert _checks({ROUTES: routes}, ROUTES) == []


def test_a_name_assigned_a_mapped_class_or_its_table_name_is_not_a_table() -> None:
    store = """
    from policyengine_api.data.v2.models import HouseholdJob
    from sqlalchemy import select

    job_model = HouseholdJob
    table_name = HouseholdJob.__tablename__
    statement = select(job_model).where(job_model.id == table_name)
    """

    assert _checks({STORE: store}, STORE) == []


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
        f"exception for {store} (sa.text(f'ANALYZE {{tables}}')) needs a "
        "function: set function to the enclosing function of its finding",
        f"exception for {script} (session.connection()) needs a function: set "
        "function to the enclosing function of its finding",
        f"exception for {rows} (text(statement)) needs a function: set function "
        "to the enclosing function of its finding",
        f"exception for {rows} (session.get_bind()) needs a function: set "
        "function to the enclosing function of its finding",
        f"exception for {rows} (mapper.local_table) needs a function: set "
        "function to the enclosing function of its finding",
    ]


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
