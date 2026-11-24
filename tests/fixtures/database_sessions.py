"""The tests' Session factories, and the few statements the ORM has no form for.

This is the tests' one session-factory module (rule api.data.orm-only, in
``SESSION_FACTORY_MODULES`` of ``tests/unit/data/orm_access_support.py``): the
only test module that creates engines, opens connections or listens for their
events. Tests take Session factories from it and run every statement through a
Session on mapped classes. docs/engineering/skills/alembic-migrations.md shows
how to write each kind of statement, under "Database statements through the
ORM".

The statements here that the ORM can't express (``TRUNCATE``, ``CREATE ROLE``,
``DROP OWNED BY``, ``DROP ROLE``, ``GRANT`` and SQLite's ``foreign_keys``
setting) are each a ``no-orm-form`` exception of the rule in
rules/registry.toml. Roles and settings inside a transaction need none:
``act_as`` and ``act_as_owner`` call Postgres's ``set_config``, which is what
``SET LOCAL ROLE`` does.
"""

from __future__ import annotations

import importlib
import re
import sqlite3
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, NamedTuple

from psycopg.pq import TransactionStatus
from sqlalchemy import (
    JSON,
    Integer,
    String,
    create_engine,
    create_mock_engine,
    delete,
    event,
    func,
    inspect,
    select,
    text,
    true,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.pool import NullPool, StaticPool

from policyengine_api.data.orm import build_session_factory
from policyengine_api.data.v1_models import Policy, V1Base
from policyengine_api.data.v2.database import build_v2_session_factory
from policyengine_api.data.v2.models import V2_METADATA
from policyengine_api.data.v2.privilege_reconciliation import (
    apply_declared_privileges,
    create_missing_roles,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping
    from pathlib import Path

    import pytest
    from sqlalchemy.engine import URL, Connection, Inspector
    from sqlalchemy.orm import registry
    from sqlalchemy.sql import ClauseElement
    from sqlmodel import Session

    from policyengine_api.data.v2.privilege_plans import ReconciliationPlan
    from policyengine_api.data.v2.privileges import DeclaredPrivilege

# A role name SET ROLE and a connection's startup options take as it is.
PLAIN_ROLE_NAME = re.compile(r"[a-z_][a-z0-9_]*")
# The role that means "no role": the session acts as the user it logged in as.
NO_ROLE = "none"
IN_MEMORY_SQLITE_URL = "sqlite://"


def _plain_role_name(role: str) -> str:
    if not PLAIN_ROLE_NAME.fullmatch(role):
        msg = f"role names here are lowercase letters, digits and _: {role!r}"
        raise ValueError(msg)
    return role


@contextmanager
def v2_owner_sessions(database_url: str) -> Iterator[sessionmaker[Session]]:
    """Yield Session factories of the disposable v2 PostgreSQL database's owner.

    The owner is the database's superuser, which owns every table. The
    engine keeps no connection pool and is disposed of on exit.
    """
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        yield build_v2_session_factory(engine)
    finally:
        engine.dispose()


@contextmanager
def single_connection_v2_sessions(
    database_url: str,
) -> Iterator[sessionmaker[Session]]:
    """Yield the v2 database owner's Session factories on a pool of one connection.

    Every Session gets the same pooled connection back, in the state the pool
    returns it in. The engine is disposed of on exit.
    """
    engine = create_engine(database_url, pool_size=1, max_overflow=0)
    try:
        yield build_v2_session_factory(engine)
    finally:
        engine.dispose()


@contextmanager
def v2_role_sessions(database_url: str, role: str) -> Iterator[sessionmaker[Session]]:
    """Yield Session factories whose every connection acts as ``role``.

    Each connection starts with ``role`` as its role (PostgreSQL's ``role``
    startup option), so every statement is checked against that role's
    privileges, as in staging and production. ``act_as_owner`` would still
    switch a transaction to the database's owner, so a test acting as a role
    uses these factories, or ``act_as`` on the owner's.
    """
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"options": f"-c role={_plain_role_name(role)}"},
    )
    try:
        yield build_v2_session_factory(engine)
    finally:
        engine.dispose()


@contextmanager
def v1_sessions(database_url: str) -> Iterator[sessionmaker[OrmSession]]:
    """Yield API v1's Session factories for the disposable MySQL database."""
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        yield build_session_factory(engine)
    finally:
        engine.dispose()


def _connect_to_sqlite(*, foreign_keys: bool) -> Callable[[], sqlite3.Connection]:
    """Return a connector to in-memory SQLite that keeps SQLAlchemy's transactions.

    sqlite3's ``autocommit=False`` mode (Python 3.12 and later) opens every
    transaction itself, so savepoints behave as they do on PostgreSQL. SQLite
    ignores ``foreign_keys`` inside a transaction, so it is set before the
    connection starts its first one.
    """
    if sys.version_info < (3, 12):
        msg = "SQLite test databases need Python 3.12's sqlite3 autocommit mode"
        raise RuntimeError(msg)

    def connect() -> sqlite3.Connection:
        sqlite_connection = sqlite3.connect(
            ":memory:", check_same_thread=False, autocommit=True
        )
        if foreign_keys:
            sqlite_connection.execute("PRAGMA foreign_keys = ON")
        sqlite_connection.autocommit = False
        return sqlite_connection

    return connect


@contextmanager
def sqlite_v2_sessions(
    *, foreign_keys: bool = False
) -> Iterator[sessionmaker[Session]]:
    """Yield Session factories of a new in-memory SQLite copy of the v2 schema.

    Every Session shares the one connection. With ``foreign_keys``, SQLite
    enforces the schema's foreign keys, which it otherwise ignores.
    """
    engine = create_engine(
        IN_MEMORY_SQLITE_URL,
        creator=_connect_to_sqlite(foreign_keys=foreign_keys),
        poolclass=StaticPool,
    )
    V2_METADATA.create_all(engine)
    try:
        yield build_v2_session_factory(engine)
    finally:
        engine.dispose()


@contextmanager
def sqlite_v2_file_sessions(path: Path) -> Iterator[sessionmaker[Session]]:
    """Yield Session factories of a SQLite file copy of the v2 schema.

    Each Session gets its own connection, so threads can run transactions at
    the same time. Every transaction starts with ``BEGIN IMMEDIATE``, which takes
    SQLite's write lock at once, as ``SELECT ... FOR UPDATE`` makes writers wait
    for each other on PostgreSQL.
    """
    engine = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 10}
    )

    @event.listens_for(engine, "connect")
    def _leave_transactions_to_sqlalchemy(
        dbapi_connection: sqlite3.Connection, _connection_record: object
    ) -> None:
        # pysqlite then never begins a transaction itself; the begin event does.
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_immediately(connection: Connection) -> None:
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    V2_METADATA.create_all(engine)
    try:
        yield build_v2_session_factory(engine)
    finally:
        engine.dispose()


def v2_schema_statements(dialect_name: str = "postgresql") -> list[str]:
    """Return the CREATE statements of the v2 schema, compiled for a dialect.

    No database is involved: a mock engine records each statement that
    ``create_all`` would send, in the order it would send them.
    """
    statements: list[str] = []

    def record(statement: Any, *_parameters: object, **_options: object) -> None:
        statements.append(str(statement.compile(dialect=recording_engine.dialect)))

    recording_engine = create_mock_engine(f"{dialect_name}://", record)
    V2_METADATA.create_all(recording_engine, checkfirst=False)
    return statements


class _SqliteV1PolicyBase(DeclarativeBase):
    """The declarative base of the SQLite copy of API v1's policy table."""


class _SqliteV1Policy(_SqliteV1PolicyBase):
    """API v1's policy table as SQLite can number it.

    API v1's key is (id, country_id, policy_hash), with id numbered by MySQL.
    SQLite numbers only a table's lone integer key, so this copy's key is
    ``id`` alone. Code still writes and reads it through API v1's ``Policy``.
    """

    __tablename__ = Policy.__tablename__
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    country_id: Mapped[str] = mapped_column(String(3))
    label: Mapped[str | None] = mapped_column(String(255))
    api_version: Mapped[str] = mapped_column(String(10))
    policy_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(255))


@contextmanager
def sqlite_v1_sessions(
    *, json_serializer: Callable[[Any], str] | None = None
) -> Iterator[sessionmaker[OrmSession]]:
    """Yield API v1's Session factories of a new in-memory SQLite copy of its schema.

    ``json_serializer`` replaces the engine's JSON serializer when given.
    """
    engine_options = (
        {} if json_serializer is None else {"json_serializer": json_serializer}
    )
    engine = create_engine(
        IN_MEMORY_SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        **engine_options,
    )
    # The policy copy first: the v1 schema then skips the table that exists.
    _SqliteV1PolicyBase.metadata.create_all(engine)
    V1Base.metadata.create_all(engine)
    try:
        yield build_session_factory(engine)
    finally:
        engine.dispose()


def serve_v1_sessions(
    monkeypatch: pytest.MonkeyPatch, sessions: sessionmaker[OrmSession]
) -> None:
    """Make API v1's own Session factory open ``sessions``' connections.

    ``policyengine_api.data.orm.get_v1_session_factory`` then builds its
    factory on ``sessions``' engine; ``monkeypatch`` undoes it after the test.
    """
    from policyengine_api.data import orm

    engine = sessions.kw["bind"]
    monkeypatch.setattr(orm, "_v1_engine", lambda: engine)
    orm.clear_v1_session_factories()


class _LocalMySqlConnector:
    """Stands in for Cloud SQL's Connector, connecting to a local MySQL server.

    The real connector's pymysql path passes every argument other than the
    instance name and driver on to pymysql, so this one does the same.
    """

    def __init__(self, database_url: URL, **_connector_options: object) -> None:
        self.database_url = database_url

    def connect(
        self, *, instance_connection_string: str, driver: str, **driver_arguments: Any
    ) -> Any:
        del instance_connection_string
        if driver != "pymysql":
            message = f"API v1's Cloud SQL engine asked for driver {driver!r}"
            raise ValueError(message)
        # pymysql ships no type stubs, so the module is loaded untyped.
        driver_module = importlib.import_module("pymysql")
        return driver_module.connect(
            host=self.database_url.host,
            port=self.database_url.port or 3306,
            **driver_arguments,
        )

    def close(self) -> None:
        """Release nothing: each connection closes when its pool closes it."""


@contextmanager
def v1_cloud_sql_sessions(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> Iterator[sessionmaker[OrmSession]]:
    """Yield API v1's own Session factory, its Cloud SQL engine on local MySQL.

    ``orm.get_v1_session_factory()`` builds the engine as production does
    (``orm._build_remote_engine``: its pool settings and connection arguments,
    such as the ``CLIENT.FOUND_ROWS`` flag), but each connection goes to the
    server at ``database_url``. ``monkeypatch`` undoes the state and settings
    after the test.
    """
    from policyengine_api.data import orm, orm_pool_events

    url = make_url(database_url)
    monkeypatch.setattr(orm, "_cloud_sql_state", orm._CloudSqlState())
    monkeypatch.setattr(
        orm, "Connector", lambda **options: _LocalMySqlConnector(url, **options)
    )
    monkeypatch.setenv("POLICYENGINE_DB_INSTANCE_CONNECTION_NAME", "local:test:mysql")
    monkeypatch.setenv("POLICYENGINE_DB_USER", url.username or "")
    monkeypatch.setenv("POLICYENGINE_DB_NAME", url.database or "")
    monkeypatch.setenv("POLICYENGINE_DB_PASSWORD", url.password or "")
    try:
        yield orm.get_v1_session_factory()
    finally:
        orm.close_v1_engines()
        # Building the engine sends the connector's logs to the runtime; undo that.
        orm_pool_events.stop_recording_connector_refresh_logs()


def _set_transaction_role(session: OrmSession, role: str) -> None:
    # set_config's third argument, true, keeps the setting to the transaction,
    # as SET LOCAL does.
    session.execute(select(func.set_config("role", role, true())))


def act_as(session: OrmSession, role: str) -> None:
    """Act as ``role`` for the rest of the session's transaction (SET LOCAL ROLE)."""
    _set_transaction_role(session, _plain_role_name(role))


def act_as_owner(session: OrmSession) -> None:
    """Act as the database's owner again, for the rest of the transaction."""
    _set_transaction_role(session, NO_ROLE)


def schema_inspector(source: OrmSession | sessionmaker[Any]) -> Inspector:
    """Return SQLAlchemy's Inspector of the database a Session or factory uses.

    A Session's Inspector reads the schema inside its transaction. Anything
    else, such as the Engine a test not yet moved to Sessions holds, is
    inspected as it is.
    """
    bind: Any = source
    if isinstance(source, OrmSession):
        bind = source.connection()
    elif isinstance(source, sessionmaker):
        bind = source.kw["bind"]
    inspector: Inspector = inspect(bind)
    return inspector


def query_plan(session: OrmSession, statement: ClauseElement) -> str:
    """Return PostgreSQL's plan for an ORM statement (EXPLAIN), its rows joined.

    A test that checks an index serves a lookup reads the plan of the ORM
    statement that does the lookup, in the session's transaction and as the
    session's role.
    """
    # The named paramstyle gives text() the :name parameters it parses.
    compiled = statement.compile(dialect=postgresql.dialect(paramstyle="named"))
    plan_rows = session.execute(text(f"EXPLAIN {compiled}"), compiled.params).scalars()
    return "\n".join(plan_rows)


@contextmanager
def recorded_statements(
    source: OrmSession | sessionmaker[Any],
) -> Iterator[list[str]]:
    """Yield a list of the SQL statements sent through ``source`` while inside."""
    engine = source.get_bind() if isinstance(source, OrmSession) else source.kw["bind"]
    statements: list[str] = []

    def record(
        _connection: object, _cursor: object, statement: str, *_arguments: object
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


class DriverConnectionState(NamedTuple):
    """The driver connection a statement ran on, as it was after the statement."""

    connection_id: int
    autocommit: bool
    in_transaction: bool


@contextmanager
def recorded_driver_connection_states(
    source: OrmSession | sessionmaker[Any],
) -> Iterator[list[DriverConnectionState]]:
    """Yield the state of the driver connection each of ``source``'s statements ran on.

    Each state is read after its statement: which connection, its autocommit
    mode, and whether it is inside a transaction. It is read after, not before,
    because psycopg sends BEGIN as part of a transaction's first statement.
    """
    engine = source.get_bind() if isinstance(source, OrmSession) else source.kw["bind"]
    states: list[DriverConnectionState] = []

    def record(connection: Any, *_arguments: object) -> None:
        driver_connection = connection.connection.dbapi_connection
        states.append(
            DriverConnectionState(
                connection_id=id(driver_connection),
                autocommit=driver_connection.autocommit,
                in_transaction=(
                    driver_connection.info.transaction_status
                    == TransactionStatus.INTRANS
                ),
            )
        )

    event.listen(engine, "after_cursor_execute", record)
    try:
        yield states
    finally:
        event.remove(engine, "after_cursor_execute", record)


def delete_all_rows(session: OrmSession, mapped_classes: registry) -> None:
    """Delete every row of every table the registry's mapped classes map."""
    for mapper in mapped_classes.mappers:
        session.execute(delete(mapper.class_))


def create_registry_tables(session: OrmSession, mapped_classes: registry) -> None:
    """Create the tables of a registry's mapped classes in the session's transaction.

    It fails if one already exists (CREATE TABLE, not IF NOT EXISTS).
    """
    mapped_classes.metadata.create_all(session.connection(), checkfirst=False)


def drop_registry_tables(session: OrmSession, mapped_classes: registry) -> None:
    """Drop whichever of a registry's tables exist, in the session's transaction.

    It skips a table that doesn't exist, as DROP TABLE IF EXISTS does.
    """
    mapped_classes.metadata.drop_all(session.connection())


def _quoted(session: OrmSession, name: str) -> str:
    return session.get_bind().dialect.identifier_preparer.quote_identifier(name)


def truncate(session: OrmSession, *models: type[Any]) -> None:
    """Empty the models' tables and every table referring to them (TRUNCATE CASCADE)."""
    tables = ", ".join(_quoted(session, model.__tablename__) for model in models)
    session.execute(text(f"TRUNCATE {tables} CASCADE"))


def drop_tables(session: OrmSession, *models: type[Any]) -> None:
    """Drop the models' tables, so later queries on them fail as on a broken catalog."""
    tables = ", ".join(_quoted(session, model.__tablename__) for model in models)
    session.execute(text(f"DROP TABLE {tables}"))


def create_role(session: OrmSession, role: str) -> None:
    """Create ``role``, which can't log in (CREATE ROLE ... NOLOGIN)."""
    quoted_role = _quoted(session, role)
    session.execute(text(f"CREATE ROLE {quoted_role} NOLOGIN"))


def drop_role(session: OrmSession, role: str) -> None:
    """Drop ``role`` and everything it owns or was granted."""
    quoted_role = _quoted(session, role)
    session.execute(text(f"DROP OWNED BY {quoted_role}"))
    session.execute(text(f"DROP ROLE {quoted_role}"))


def grant(session: OrmSession, privileges: str, *, on: type[Any], to: str) -> None:
    """Grant ``privileges`` on a model's table to a role, as in ``GRANT ... ON TABLE``.

    ``privileges`` is GRANT's privilege list, such as ``"SELECT, INSERT"`` or
    ``"UPDATE (label, code)"``.
    """
    table = f"public.{_quoted(session, on.__tablename__)}"
    quoted_role = _quoted(session, to)
    session.execute(text(f"GRANT {privileges} ON TABLE {table} TO {quoted_role}"))


def grant_declared_v2_privileges(
    database_url: str,
    declared: Mapping[str, Mapping[str, frozenset[DeclaredPrivilege]]],
) -> ReconciliationPlan:
    """Create the declared roles that are missing and grant their privileges.

    It does what ``reconcile_v2_privileges.py apply --create-missing-roles``
    does, in one transaction as the database's owner, and returns the plan.
    """
    with v2_owner_sessions(database_url) as sessions, sessions.begin() as session:
        create_missing_roles(session, declared)
        plan, _default_privileges = apply_declared_privileges(session, declared)
    return plan
