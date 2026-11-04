"""Records of the v1 Cloud SQL pool's connections and database errors.

The pool records each database connection opening, being invalidated (hard or
soft) and closing, with its socket's file descriptor and local port, so a
failed request to the simulation service (``simulation_entrypoint.request``)
can be compared with database reconnects in the same process. A file
descriptor number is free to be reused as soon as its socket closes, so a
database connection that opens with the number of an HTTP connection that is
still open, with no close recorded for that number in between, would show that
the HTTP connection's socket had been closed underneath it.

- ``connect`` saves the socket's file descriptor and local port in the
  connection's ``info``, because pymysql drops its socket (``_force_close``
  sets ``_sock`` to None) before it raises the error that invalidates the
  connection. ``invalidate``, ``soft_invalidate`` and ``close`` read them back.
  ``close_detached`` has no pool entry, so it reads them from a weak map from
  driver connection to saved socket.
- ``close`` covers a connection closed for recycling, an overflow connection
  returned to a full pool, the pool-wide recycle after a failed pre-ping, an
  invalidation, and ``dispose()``.
- ``handle_error`` records each database error with the error's type, the
  driver's error code and the OSError in its chain, and whether the error
  came from the checkout ping (``pool_pre_ping``) and was a disconnect. A
  failed ping invalidates the connection with a bare
  ``sqlalchemy.exc.InvalidatePoolError``, so only this record has the cause.

Checkouts are not recorded: almost every request checks out a connection.
Records carry error types and codes, never messages.

The Cloud SQL connector logs each certificate refresh at DEBUG, and the
observability runtime's standard-library log handler skips ``google.`` loggers,
so the connector's refresh messages are sent to the runtime here, at INFO.
"""

from __future__ import annotations

import contextlib
import logging
import weakref
from typing import TYPE_CHECKING, Any

from sqlalchemy import event
from typing_extensions import override

from policyengine_api.observability import get_runtime
from policyengine_api.observability.sockets import (
    os_error_attributes,
    prefixed,
    socket_identity,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy import Engine
    from sqlalchemy.engine import ExceptionContext
    from sqlalchemy.pool import ConnectionPoolEntry, Pool

CONNECT_EVENT = "database_pool.connect"
INVALIDATE_EVENT = "database_pool.invalidate"
SOFT_INVALIDATE_EVENT = "database_pool.soft_invalidate"
CLOSE_EVENT = "database_pool.close"
CLOSE_DETACHED_EVENT = "database_pool.close_detached"
ERROR_EVENT = "database_pool.error"
# The key in a pool entry's ``info`` that holds its socket's identity.
SOCKET_INFO_KEY = "policyengine_api.socket"
# The module that logs the lazy refresh strategy's certificate fetches.
CONNECTOR_REFRESH_LOGGER = "google.cloud.sql.connector.lazy"

# Driver connection -> its saved socket identity, for close_detached, which
# gets no pool entry. Entries go when the driver connection is collected.
_detached_sockets: weakref.WeakKeyDictionary[object, dict[str, int]] = (
    weakref.WeakKeyDictionary()
)
# The connector logger's level and propagation before
# record_connector_refresh_logs changed them.
_connector_logger_settings: dict[str, Any] = {}


def record_pool_events(target: Engine | Pool) -> None:
    """Record ``target``'s connects, invalidations, closes and database errors.

    Also send the Cloud SQL connector's certificate refresh messages to the
    logs at INFO. ``handle_error`` is an engine event, so it is recorded only
    when ``target`` is an Engine.
    """
    event.listen(target, "connect", _record_connect)
    event.listen(target, "invalidate", _record_invalidate)
    event.listen(target, "soft_invalidate", _record_soft_invalidate)
    event.listen(target, "close", _record_close)
    event.listen(target, "close_detached", _record_close_detached)
    if hasattr(target, "dialect"):
        event.listen(target, "handle_error", _record_error)
    record_connector_refresh_logs()


def _driver_socket(driver_connection: object) -> dict[str, int]:
    """Return the file descriptor and local port of the driver's open socket.

    pymysql keeps its socket in ``_sock``. It is read as an attribute, without
    importing the driver (rule api.data.sqlalchemy-and-alembic-only).
    """
    sock = getattr(driver_connection, "_sock", None)
    return {} if sock is None else socket_identity(sock)


def _saved_socket(connection_record: ConnectionPoolEntry) -> dict[str, int | str]:
    saved = connection_record.info.get(SOCKET_INFO_KEY, {})
    return prefixed("database_connection.", saved)


def _emit(event_name: str, severity: str, attributes: Mapping[str, object]) -> None:
    # Recording must never change the pool's behavior.
    with contextlib.suppress(Exception):
        get_runtime().event(
            event_name,
            severity=severity,
            attributes={"database_pool.engine": "v1_cloud_sql", **attributes},
        )


def _error_attributes(prefix: str, error: BaseException) -> dict[str, int | str]:
    """Return an error's type, driver error code and OSError, without its message.

    A DBAPI error's first argument is the driver's error code, such as MySQL's
    2013 (lost connection); SQLAlchemy keeps the driver's error in ``orig``.
    """
    attributes: dict[str, int | str] = {f"{prefix}error_type": type(error).__name__}
    driver_error = getattr(error, "orig", None) or error
    if driver_error.args and isinstance(driver_error.args[0], int):
        attributes[f"{prefix}driver_error_code"] = driver_error.args[0]
    attributes.update(prefixed(prefix, os_error_attributes(error)))
    return attributes


def _record_connect(
    driver_connection: object, connection_record: ConnectionPoolEntry
) -> None:
    with contextlib.suppress(Exception):
        identity = _driver_socket(driver_connection)
        connection_record.info[SOCKET_INFO_KEY] = identity
        with contextlib.suppress(TypeError):
            _detached_sockets[driver_connection] = identity
        _emit(CONNECT_EVENT, "INFO", _saved_socket(connection_record))


def _record_invalidation(
    event_name: str,
    connection_record: ConnectionPoolEntry,
    error: BaseException | None,
) -> None:
    with contextlib.suppress(Exception):
        attributes: dict[str, object] = dict(_saved_socket(connection_record))
        if error is not None:
            attributes.update(_error_attributes("database_failure.", error))
        _emit(event_name, "WARNING", attributes)


def _record_invalidate(
    _driver_connection: object,
    connection_record: ConnectionPoolEntry,
    error: BaseException | None,
) -> None:
    _record_invalidation(INVALIDATE_EVENT, connection_record, error)


def _record_soft_invalidate(
    _driver_connection: object,
    connection_record: ConnectionPoolEntry,
    error: BaseException | None,
) -> None:
    _record_invalidation(SOFT_INVALIDATE_EVENT, connection_record, error)


def _record_close(
    _driver_connection: object, connection_record: ConnectionPoolEntry
) -> None:
    with contextlib.suppress(Exception):
        _emit(CLOSE_EVENT, "INFO", _saved_socket(connection_record))


def _record_close_detached(driver_connection: object) -> None:
    with contextlib.suppress(Exception):
        saved: dict[str, int] = {}
        # A driver connection that cannot be weakly referenced was never saved.
        with contextlib.suppress(TypeError):
            saved = _detached_sockets.get(driver_connection, {})
        _emit(CLOSE_DETACHED_EVENT, "INFO", prefixed("database_connection.", saved))


def _record_error(context: ExceptionContext) -> None:
    with contextlib.suppress(Exception):
        attributes: dict[str, object] = {
            "database_error.is_pre_ping": context.is_pre_ping,
            "database_error.is_disconnect": context.is_disconnect,
            **_error_attributes("database_error.", context.original_exception),
        }
        _emit(
            ERROR_EVENT,
            "WARNING" if context.is_disconnect else "INFO",
            attributes,
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

    Every message the connector's lazy refresh module logs is sent: a refresh
    starting, completing or failing, the new certificate's expiry, and, for
    each new database connection, that the cached certificate is still valid.
    Propagation stops at that module's logger, so its DEBUG messages reach no
    other handler. The logger gets one handler however often this is called,
    for however many engines; stop_recording_connector_refresh_logs undoes it.
    """
    connector_logger = logging.getLogger(CONNECTOR_REFRESH_LOGGER)
    if any(
        isinstance(handler, ConnectorRefreshLogHandler)
        for handler in connector_logger.handlers
    ):
        return
    _connector_logger_settings.update(
        level=connector_logger.level, propagate=connector_logger.propagate
    )
    connector_logger.addHandler(ConnectorRefreshLogHandler())
    connector_logger.setLevel(logging.DEBUG)
    connector_logger.propagate = False


def stop_recording_connector_refresh_logs() -> None:
    """Remove the connector log handler; restore the logger's level and propagation."""
    connector_logger = logging.getLogger(CONNECTOR_REFRESH_LOGGER)
    for handler in list(connector_logger.handlers):
        if isinstance(handler, ConnectorRefreshLogHandler):
            connector_logger.removeHandler(handler)
    if _connector_logger_settings:
        connector_logger.setLevel(_connector_logger_settings["level"])
        connector_logger.propagate = _connector_logger_settings["propagate"]
        _connector_logger_settings.clear()
