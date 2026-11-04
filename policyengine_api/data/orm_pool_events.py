"""Records of the v1 Cloud SQL pool opening and invalidating connections.

Each record carries the database socket's file descriptor and local port. A
``simulation_entrypoint.request`` record carries the same for its HTTP
connection, so the two can be compared when a request to the simulation
service fails after a database reconnect in the same process. A database
connection that opens with the file descriptor number of an HTTP connection
that is still in use would show that the HTTP connection's socket had been
closed underneath it and its number reused.

Checkouts are not recorded: almost every request checks out a connection.

The Cloud SQL connector logs each certificate refresh at DEBUG, and the
observability runtime's standard-library log handler skips ``google.`` loggers,
so the connector's refresh messages are sent to the runtime here, at INFO.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from sqlalchemy import event
from typing_extensions import override

from policyengine_api.observability import get_runtime
from policyengine_api.observability.sockets import (
    os_error_attributes,
    prefixed,
    socket_identity,
)

if TYPE_CHECKING:
    from sqlalchemy import Engine
    from sqlalchemy.pool import ConnectionPoolEntry, Pool

CONNECT_EVENT = "database_pool.connect"
INVALIDATE_EVENT = "database_pool.invalidate"
SOFT_INVALIDATE_EVENT = "database_pool.soft_invalidate"
# The module that logs the lazy refresh strategy's certificate fetches.
CONNECTOR_REFRESH_LOGGER = "google.cloud.sql.connector.lazy"


def record_pool_events(target: Engine | Pool) -> None:
    """Record connects and invalidations on ``target``'s pool.

    Also send the Cloud SQL connector's certificate refresh messages to the
    logs at INFO.
    """
    event.listen(target, "connect", _record_connect)
    event.listen(target, "invalidate", _record_invalidate)
    event.listen(target, "soft_invalidate", _record_soft_invalidate)
    record_connector_refresh_logs()


def _database_socket(pooled_connection: object) -> dict[str, int | str]:
    """Return the file descriptor and local port of the driver's socket.

    pymysql keeps its socket in ``_sock``. It is read as an attribute, without
    importing the driver (rule api.data.sqlalchemy-and-alembic-only), and is
    absent for other drivers and after the driver closes a broken connection.
    """
    sock = getattr(pooled_connection, "_sock", None)
    if sock is None:
        return {}
    return prefixed("database_connection.", socket_identity(sock))


def _emit(event_name: str, severity: str, attributes: dict[str, int | str]) -> None:
    # Recording must never change the pool's behavior.
    with contextlib.suppress(Exception):
        get_runtime().event(
            event_name,
            severity=severity,
            attributes={"database_pool.engine": "v1_cloud_sql", **attributes},
        )


def _record_connect(
    pooled_connection: object, _connection_record: ConnectionPoolEntry
) -> None:
    with contextlib.suppress(Exception):
        _emit(CONNECT_EVENT, "INFO", _database_socket(pooled_connection))


def _invalidation_attributes(
    pooled_connection: object, error: BaseException | None
) -> dict[str, int | str]:
    attributes = _database_socket(pooled_connection)
    if error is None:
        return attributes
    attributes["database_failure.error_type"] = type(error).__name__
    # A DBAPI error's first argument is the driver's error code, such as
    # MySQL's 2013 (lost connection); SQLAlchemy wraps it in ``orig``.
    driver_error = getattr(error, "orig", None) or error
    if driver_error.args and isinstance(driver_error.args[0], int):
        attributes["database_failure.driver_error_code"] = driver_error.args[0]
    attributes.update(prefixed("database_failure.", os_error_attributes(error)))
    return attributes


def _record_invalidate(
    pooled_connection: object,
    _connection_record: ConnectionPoolEntry,
    error: BaseException | None,
) -> None:
    with contextlib.suppress(Exception):
        _emit(
            INVALIDATE_EVENT,
            "WARNING",
            _invalidation_attributes(pooled_connection, error),
        )


def _record_soft_invalidate(
    pooled_connection: object,
    _connection_record: ConnectionPoolEntry,
    error: BaseException | None,
) -> None:
    with contextlib.suppress(Exception):
        _emit(
            SOFT_INVALIDATE_EVENT,
            "WARNING",
            _invalidation_attributes(pooled_connection, error),
        )


class ConnectorRefreshLogHandler(logging.Handler):
    """Send the Cloud SQL connector's refresh messages to the runtime, at INFO."""

    @override
    def emit(self, record: logging.LogRecord) -> None:
        # Logging must never affect the connector.
        with contextlib.suppress(Exception):
            severity = "INFO" if record.levelno <= logging.INFO else record.levelname
            get_runtime().log(
                record.getMessage(),
                severity=severity,
                attributes={"logger_name": record.name},
            )


def record_connector_refresh_logs() -> None:
    """Send the connector's certificate refresh messages to the logs at INFO.

    Propagation stops at the connector's logger, so its DEBUG messages reach no
    other handler. Calling this again changes nothing.
    """
    connector_logger = logging.getLogger(CONNECTOR_REFRESH_LOGGER)
    if any(
        isinstance(handler, ConnectorRefreshLogHandler)
        for handler in connector_logger.handlers
    ):
        return
    connector_logger.addHandler(ConnectorRefreshLogHandler())
    connector_logger.setLevel(logging.DEBUG)
    connector_logger.propagate = False
