"""Records of the v1 pool's connections, database errors and connector refreshes.

The engines here are real SQLAlchemy engines with pre-ping, over in-memory
SQLite connections that, like pymysql's, keep a socket in ``_sock`` and drop
it (``_sock = None``) when the connection breaks, before the error is raised.
"""

import errno
import logging
import socket
import sqlite3
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, exc
from sqlalchemy.pool import QueuePool

from policyengine_api.data import orm_pool_events

ENGINE_FIELD = {"database_pool.engine": "v1_cloud_sql"}


class RecordingRuntime:
    """Stands in for the observability runtime and keeps every event and log."""

    def __init__(self):
        self.events = []
        self.logs = []

    def event(self, name, *, severity="INFO", attributes=None):
        self.events.append((name, severity, dict(attributes)))

    def log(self, message, *, severity="INFO", attributes=None):
        self.logs.append((message, severity, dict(attributes)))

    def names(self):
        return [name for name, _severity, _attributes in self.events]


class SocketCarryingConnection(sqlite3.Connection):
    """A SQLite connection that keeps a socket in ``_sock``, as pymysql's does."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self.socket_fields = {
            "database_connection.fd": self._sock.fileno(),
            "database_connection.local_port": self._sock.getsockname()[1],
        }

    def break_like_pymysql(self, error=None):
        """Lose the connection: drop the socket, as pymysql's _force_close does.

        With ``error``, the next ping raises it instead of finding a closed
        SQLite database.
        """
        self._sock.close()
        self._sock = None
        self.ping_error = error
        super().close()

    def cursor(self, *args, **kwargs):
        if getattr(self, "ping_error", None) is not None:
            raise self.ping_error
        return super().cursor(*args, **kwargs)

    def close(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        super().close()


class LostConnectionError(Exception):
    """A driver error whose first argument is the driver's error code."""


class OperationalError(sqlite3.OperationalError):
    """Shaped like pymysql.err.OperationalError: (code, message) arguments.

    It subclasses SQLite's error so that SQLAlchemy's SQLite dialect treats it
    as a DBAPI error, as the MySQL dialect treats pymysql's.
    """


def pymysql_lost_connection_error():
    """Return OperationalError(2013, ...) caused by a ConnectionResetError.

    This is how pymysql raises a lost connection: its socket read fails, and
    _read_bytes raises OperationalError(CR_SERVER_LOST, ...) from the OSError.
    """
    os_error = ConnectionResetError(errno.ECONNRESET, "Connection reset by peer")
    driver_error = OperationalError(
        2013, "Lost connection to MySQL server during query"
    )
    driver_error.__cause__ = os_error
    return driver_error


def lost_connection_error():
    """Return a driver error caused by a ConnectionResetError, as pymysql raises it."""
    os_error = ConnectionResetError(errno.ECONNRESET, "Connection reset by peer")
    driver_error = LostConnectionError(2013, "Lost connection to MySQL server")
    driver_error.__cause__ = os_error
    return driver_error


@pytest.fixture
def runtime(monkeypatch):
    recording_runtime = RecordingRuntime()
    monkeypatch.setattr(orm_pool_events, "get_runtime", lambda: recording_runtime)
    return recording_runtime


@pytest.fixture
def connector_logger():
    """Yield the connector's refresh logger, restored afterwards."""
    connector_logger = logging.getLogger(orm_pool_events.CONNECTOR_REFRESH_LOGGER)
    saved_handlers = list(connector_logger.handlers)
    saved_level = connector_logger.level
    saved_propagate = connector_logger.propagate
    yield connector_logger
    connector_logger.handlers[:] = saved_handlers
    connector_logger.setLevel(saved_level)
    connector_logger.propagate = saved_propagate


@pytest.fixture
def engine_factory(connector_logger):
    """Build pre-ping engines over socket-carrying SQLite connections."""
    engines = []
    connections = []

    def build(**pool_options):
        def open_connection():
            connection = sqlite3.connect(
                ":memory:",
                factory=SocketCarryingConnection,
                check_same_thread=False,
            )
            connections.append(connection)
            return connection

        engine = create_engine(
            "sqlite://",
            creator=open_connection,
            poolclass=QueuePool,
            pool_pre_ping=True,
            **pool_options,
        )
        orm_pool_events.record_pool_events(engine)
        engines.append(engine)
        return engine, connections

    yield build
    for engine in engines:
        engine.dispose()


def test_failed_pre_ping_records_its_cause_and_the_lost_socket(runtime, engine_factory):
    engine, connections = engine_factory(pool_size=1, max_overflow=0)
    with engine.connect() as connection:
        connection.exec_driver_sql("select 1")
    [first] = connections
    first.break_like_pymysql()

    with engine.connect() as connection:
        connection.exec_driver_sql("select 1")

    assert runtime.names() == [
        "database_pool.connect",
        "database_pool.error",
        "database_pool.invalidate",
        "database_pool.close",
        "database_pool.connect",
    ]
    connect, error, invalidate, close, reconnect = runtime.events
    second = connections[1]
    assert connect[1:] == ("INFO", {**ENGINE_FIELD, **first.socket_fields})
    # The ping's own error, which the invalidation does not carry.
    assert error[1:] == (
        "WARNING",
        {
            **ENGINE_FIELD,
            "database_error.is_pre_ping": True,
            "database_error.is_disconnect": True,
            "database_error.error_type": "ProgrammingError",
        },
    )
    # The driver dropped its socket, so these come from what connect saved.
    assert invalidate[1:] == (
        "WARNING",
        {
            **ENGINE_FIELD,
            **first.socket_fields,
            "database_failure.error_type": "InvalidatePoolError",
        },
    )
    assert close[1:] == ("INFO", {**ENGINE_FIELD, **first.socket_fields})
    assert reconnect[1:] == ("INFO", {**ENGINE_FIELD, **second.socket_fields})


def test_failed_pre_ping_records_the_driver_code_and_errno(
    runtime, engine_factory, monkeypatch
):
    engine, connections = engine_factory(pool_size=1, max_overflow=0)
    # The MySQL dialect counts error 2013 as a disconnect; SQLite's doesn't.
    sqlite_is_disconnect = engine.dialect.is_disconnect
    monkeypatch.setattr(
        engine.dialect,
        "is_disconnect",
        lambda error, *arguments: (
            isinstance(error, OperationalError)
            or sqlite_is_disconnect(error, *arguments)
        ),
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("select 1")
    [first] = connections
    first.break_like_pymysql(pymysql_lost_connection_error())

    with engine.connect() as connection:
        connection.exec_driver_sql("select 1")

    assert runtime.names() == [
        "database_pool.connect",
        "database_pool.error",
        "database_pool.invalidate",
        "database_pool.close",
        "database_pool.connect",
    ]
    _connect, error, invalidate, close, _reconnect = runtime.events
    assert error[1:] == (
        "WARNING",
        {
            **ENGINE_FIELD,
            "database_error.is_pre_ping": True,
            "database_error.is_disconnect": True,
            "database_error.error_type": "OperationalError",
            "database_error.driver_error_code": 2013,
            "database_error.os_error_type": "ConnectionResetError",
            "database_error.os_errno": errno.ECONNRESET,
            "database_error.os_errno_name": "ECONNRESET",
        },
    )
    assert invalidate[2] == {
        **ENGINE_FIELD,
        **first.socket_fields,
        "database_failure.error_type": "InvalidatePoolError",
    }
    assert close[2] == {**ENGINE_FIELD, **first.socket_fields}


def test_invalidations_keep_the_socket_and_the_driver_error(runtime, engine_factory):
    engine, connections = engine_factory(pool_size=2, max_overflow=0)

    with engine.connect() as connection:
        connections[0].break_like_pymysql()
        connection.invalidate(lost_connection_error())
    with engine.connect() as connection:
        connection.connection.invalidate(lost_connection_error(), soft=True)

    expected_failure = {
        "database_failure.error_type": "LostConnectionError",
        "database_failure.driver_error_code": 2013,
        "database_failure.os_error_type": "ConnectionResetError",
        "database_failure.os_errno": errno.ECONNRESET,
        "database_failure.os_errno_name": "ECONNRESET",
    }
    invalidations = [
        (name, attributes)
        for name, _severity, attributes in runtime.events
        if "invalidate" in name
    ]
    assert invalidations == [
        (
            "database_pool.invalidate",
            {**ENGINE_FIELD, **connections[0].socket_fields, **expected_failure},
        ),
        (
            "database_pool.soft_invalidate",
            {**ENGINE_FIELD, **connections[1].socket_fields, **expected_failure},
        ),
    ]


def test_closes_are_recorded_with_the_saved_socket(runtime, engine_factory):
    engine, connections = engine_factory(pool_size=1, max_overflow=1, pool_recycle=3600)
    pooled = engine.connect()
    overflow = engine.connect()
    pooled.close()
    # The pool is full, so the overflow connection is closed on its return.
    overflow.close()
    recycled_events = len(runtime.events)
    engine.pool._recycle = 0  # The next checkout recycles the pooled connection.
    engine.connect().close()
    detached = engine.connect()
    detached.detach()
    detached.close()
    engine.dispose()

    overflow_close = runtime.events[recycled_events - 1]
    assert overflow_close == (
        "database_pool.close",
        "INFO",
        {**ENGINE_FIELD, **connections[1].socket_fields},
    )
    after_recycle = runtime.events[recycled_events:]
    assert after_recycle[:2] == [
        (
            "database_pool.close",
            "INFO",
            {**ENGINE_FIELD, **connections[0].socket_fields},
        ),
        (
            "database_pool.connect",
            "INFO",
            {**ENGINE_FIELD, **connections[2].socket_fields},
        ),
    ]
    detached_closes = [
        attributes
        for name, _severity, attributes in runtime.events
        if name == "database_pool.close_detached"
    ]
    # The detached connection is the last one opened; dispose() then has
    # nothing left to close.
    assert detached_closes == [{**ENGINE_FIELD, **connections[-1].socket_fields}]
    assert "database_pool.checkout" not in runtime.names()


def test_statement_errors_are_recorded_without_their_message(runtime, engine_factory):
    engine, _connections = engine_factory(pool_size=1, max_overflow=0)

    with engine.connect() as connection, pytest.raises(exc.OperationalError):
        connection.exec_driver_sql("select * from a_missing_table")

    [error] = [event for event in runtime.events if event[0] == "database_pool.error"]
    assert error[1:] == (
        "INFO",
        {
            **ENGINE_FIELD,
            "database_error.is_pre_ping": False,
            "database_error.is_disconnect": False,
            "database_error.error_type": "OperationalError",
        },
    )


def test_connection_without_a_driver_socket_is_recorded_without_one(runtime):
    pool_entry = SimpleNamespace(info={})

    orm_pool_events._record_connect(object(), pool_entry)
    orm_pool_events._record_invalidate(object(), pool_entry, None)
    orm_pool_events._record_close(object(), pool_entry)
    orm_pool_events._record_close_detached(object())

    assert runtime.events == [
        ("database_pool.connect", "INFO", ENGINE_FIELD),
        ("database_pool.invalidate", "WARNING", ENGINE_FIELD),
        ("database_pool.close", "INFO", ENGINE_FIELD),
        ("database_pool.close_detached", "INFO", ENGINE_FIELD),
    ]


@pytest.mark.usefixtures("connector_logger")
def test_engine_listens_for_connections_closes_and_errors_only():
    engine = create_engine("sqlite://", poolclass=QueuePool)

    orm_pool_events.record_pool_events(engine)

    for event_name, listener in (
        ("connect", orm_pool_events._record_connect),
        ("invalidate", orm_pool_events._record_invalidate),
        ("soft_invalidate", orm_pool_events._record_soft_invalidate),
        ("close", orm_pool_events._record_close),
        ("close_detached", orm_pool_events._record_close_detached),
        ("handle_error", orm_pool_events._record_error),
    ):
        assert event.contains(engine, event_name, listener), event_name
    assert not engine.pool.dispatch.checkout
    engine.dispose()


def test_connector_refresh_messages_reach_the_logs_as_fixed_text(
    runtime, connector_logger
):
    orm_pool_events.record_connector_refresh_logs()
    orm_pool_events.record_connector_refresh_logs()
    lazy_logger = logging.getLogger("google.cloud.sql.connector.lazy")
    # The messages the connector's lazy refresh module logs, already formatted
    # as it formats them, with the instance's connection name in front.
    prefix = "['project:region:instance']: "
    connector_messages = [
        f"{prefix}Connection info refresh operation started",
        f"{prefix}Connection info refresh operation failed: "
        "403 Forbidden: the caller lacks cloudsql.instances.connect",
        f"{prefix}Connection info refresh operation completed successfully",
        f"{prefix}Current certificate expiration = 2026-11-04 12:00:00+00:00",
        f"{prefix}Connection info is still valid, using cached info",
        f"{prefix}a message the connector does not log",
    ]
    for message in connector_messages:
        lazy_logger.debug(message)
    timeout = TimeoutError("timed out")
    lazy_logger.warning(
        "['project:region:instance']: Connection info refresh operation failed",
        exc_info=(TimeoutError, timeout, None),
    )

    logger_field = {"logger_name": "google.cloud.sql.connector.lazy"}
    assert runtime.logs == [
        ("Connection info refresh operation started", "INFO", logger_field),
        ("Connection info refresh operation failed", "INFO", logger_field),
        (
            "Connection info refresh operation completed successfully",
            "INFO",
            logger_field,
        ),
        (
            "Current certificate expiration",
            "INFO",
            {**logger_field, "certificate_expiration": "2026-11-04 12:00:00+00:00"},
        ),
        ("Connection info is still valid, using cached info", "INFO", logger_field),
        (
            "Connection info refresh operation failed",
            "WARNING",
            {**logger_field, "error_type": "TimeoutError"},
        ),
    ]
    assert len(connector_logger.handlers) == 1
    assert connector_logger.propagate is False


def test_failing_runtime_leaves_the_pool_working(monkeypatch, engine_factory):
    def failing_runtime():
        msg = "telemetry is down"
        raise RuntimeError(msg)

    monkeypatch.setattr(orm_pool_events, "get_runtime", failing_runtime)
    engine, connections = engine_factory(pool_size=1, max_overflow=0)
    with engine.connect() as connection:
        connection.exec_driver_sql("select 1")
    connections[0].break_like_pymysql()

    with engine.connect() as connection:
        assert connection.exec_driver_sql("select 1").scalar() == 1
    logging.getLogger(orm_pool_events.CONNECTOR_REFRESH_LOGGER).debug("refresh")


def test_dispose_records_the_close_of_each_pooled_connection(runtime, engine_factory):
    engine, connections = engine_factory(pool_size=1, max_overflow=0)
    engine.connect().close()

    engine.dispose()

    assert runtime.events[-1] == (
        "database_pool.close",
        "INFO",
        {**ENGINE_FIELD, **connections[0].socket_fields},
    )


def test_one_handler_however_many_engines_and_stopping_restores_the_logger(
    engine_factory, connector_logger
):
    connector_logger.setLevel(logging.WARNING)
    connector_logger.propagate = True

    engine_factory(pool_size=1, max_overflow=0)
    engine_factory(pool_size=1, max_overflow=0)

    handlers = [
        handler
        for handler in connector_logger.handlers
        if isinstance(handler, orm_pool_events.ConnectorRefreshLogHandler)
    ]
    assert len(handlers) == 1
    assert connector_logger.level == logging.DEBUG
    assert connector_logger.propagate is False

    orm_pool_events.stop_recording_connector_refresh_logs()

    assert not any(
        isinstance(handler, orm_pool_events.ConnectorRefreshLogHandler)
        for handler in connector_logger.handlers
    )
    assert connector_logger.level == logging.WARNING
    assert connector_logger.propagate is True
