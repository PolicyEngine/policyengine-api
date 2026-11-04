"""Records of the v1 pool's connects and invalidations, and of connector refreshes."""

import errno
import logging
import socket

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import QueuePool

from policyengine_api.data import orm_pool_events


class RecordingRuntime:
    """Stands in for the observability runtime and keeps every event and log."""

    def __init__(self):
        self.events = []
        self.logs = []

    def event(self, name, *, severity="INFO", attributes=None):
        self.events.append((name, severity, dict(attributes)))

    def log(self, message, *, severity="INFO", attributes=None):
        self.logs.append((message, severity, dict(attributes)))


class FakeDriverConnection:
    """A DBAPI connection that, like pymysql's, keeps its socket in ``_sock``."""

    def __init__(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self.socket_fields = {
            "database_connection.fd": self._sock.fileno(),
            "database_connection.local_port": self._sock.getsockname()[1],
        }

    def rollback(self):
        pass

    def close(self):
        self._sock.close()


class FakeOperationalError(Exception):
    """A driver error whose first argument is the driver's error code."""


def lost_connection_error():
    """Return a driver error caused by a ConnectionResetError, as pymysql raises it."""
    os_error = ConnectionResetError(errno.ECONNRESET, "Connection reset by peer")
    driver_error = FakeOperationalError(
        2013, "Lost connection to MySQL server during query"
    )
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
    saved = (list(connector_logger.handlers), connector_logger.level)
    saved_propagate = connector_logger.propagate
    yield connector_logger
    connector_logger.handlers[:] = saved[0]
    connector_logger.setLevel(saved[1])
    connector_logger.propagate = saved_propagate


@pytest.mark.usefixtures("connector_logger")
def test_pool_records_connects_and_invalidations_with_the_socket(runtime):
    connections = []

    def open_connection():
        connections.append(FakeDriverConnection())
        return connections[-1]

    pool = QueuePool(open_connection, pool_size=2, max_overflow=0)
    orm_pool_events.record_pool_events(pool)

    first = pool.connect()
    first.invalidate(lost_connection_error())
    pool.connect().close()
    # This checkout reuses the pooled connection, which records nothing.
    reused = pool.connect()
    reused.invalidate(lost_connection_error(), soft=True)
    reused.close()

    first_connection, second_connection = connections
    names = [name for name, _severity, _attributes in runtime.events]
    assert names == [
        "database_pool.connect",
        "database_pool.invalidate",
        "database_pool.connect",
        "database_pool.soft_invalidate",
    ]
    connect, invalidate, reconnect, soft_invalidate = runtime.events
    engine_field = {"database_pool.engine": "v1_cloud_sql"}
    assert connect[1:] == ("INFO", {**engine_field, **first_connection.socket_fields})
    assert reconnect[1:] == (
        "INFO",
        {**engine_field, **second_connection.socket_fields},
    )
    expected_failure = {
        "database_failure.error_type": "FakeOperationalError",
        "database_failure.driver_error_code": 2013,
        "database_failure.os_error_type": "ConnectionResetError",
        "database_failure.os_errno": errno.ECONNRESET,
        "database_failure.os_errno_name": "ECONNRESET",
    }
    assert invalidate[1:] == (
        "WARNING",
        {**engine_field, **first_connection.socket_fields, **expected_failure},
    )
    assert soft_invalidate[1:] == (
        "WARNING",
        {**engine_field, **second_connection.socket_fields, **expected_failure},
    )
    pool.dispose()


def test_connection_without_a_driver_socket_is_recorded_without_one(runtime):
    orm_pool_events._record_connect(object(), None)
    orm_pool_events._record_invalidate(object(), None, None)

    assert runtime.events == [
        ("database_pool.connect", "INFO", {"database_pool.engine": "v1_cloud_sql"}),
        (
            "database_pool.invalidate",
            "WARNING",
            {"database_pool.engine": "v1_cloud_sql"},
        ),
    ]


@pytest.mark.usefixtures("connector_logger")
def test_engine_listens_for_connects_and_invalidations_only():
    engine = create_engine("mysql+pymysql://", creator=FakeDriverConnection)

    orm_pool_events.record_pool_events(engine)

    assert event.contains(engine, "connect", orm_pool_events._record_connect)
    assert event.contains(engine, "invalidate", orm_pool_events._record_invalidate)
    assert event.contains(
        engine, "soft_invalidate", orm_pool_events._record_soft_invalidate
    )
    assert not engine.pool.dispatch.checkout
    engine.dispose()


def test_connector_refresh_messages_reach_the_logs_at_info(runtime, connector_logger):
    orm_pool_events.record_connector_refresh_logs()
    orm_pool_events.record_connector_refresh_logs()

    logging.getLogger("google.cloud.sql.connector.lazy").debug(
        "['project:region:instance']: Connection info refresh operation started"
    )
    logging.getLogger("google.cloud.sql.connector.lazy").warning("refresh failed")

    assert runtime.logs == [
        (
            "['project:region:instance']: Connection info refresh operation started",
            "INFO",
            {"logger_name": "google.cloud.sql.connector.lazy"},
        ),
        (
            "refresh failed",
            "WARNING",
            {"logger_name": "google.cloud.sql.connector.lazy"},
        ),
    ]
    assert len(connector_logger.handlers) == 1
    assert connector_logger.propagate is False


def test_failing_runtime_leaves_the_pool_working(monkeypatch, connector_logger):
    def failing_runtime():
        msg = "telemetry is down"
        raise RuntimeError(msg)

    monkeypatch.setattr(orm_pool_events, "get_runtime", failing_runtime)
    pool = QueuePool(FakeDriverConnection, pool_size=1, max_overflow=0)
    orm_pool_events.record_pool_events(pool)

    connection = pool.connect()
    connection.invalidate(lost_connection_error())
    logging.getLogger(connector_logger.name).debug("refresh started")
    pool.connect().close()
    pool.dispose()
