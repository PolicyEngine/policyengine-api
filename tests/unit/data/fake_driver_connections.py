"""A stand-in for pymysql's connections, for the v1 pool event tests.

``SocketCarryingConnection`` is an in-memory SQLite connection that, like
pymysql's, keeps a socket in ``_sock`` and drops it (``_sock = None``) when the
connection breaks, before the error is raised. The error builders return the
driver errors pymysql raises for a lost connection. This module is the fake
database driver beneath SQLAlchemy, so it uses only ``sqlite3`` and
``socket``.
"""

from __future__ import annotations

import errno
import socket
import sqlite3
from typing import TYPE_CHECKING, Any, TypeVar, overload

if TYPE_CHECKING:
    from collections.abc import Callable

CursorType = TypeVar("CursorType", bound=sqlite3.Cursor)


class SocketCarryingConnection(sqlite3.Connection):
    """A SQLite connection that keeps a socket in ``_sock``, as pymysql's does."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._sock: socket.socket | None = socket.socket(
            socket.AF_INET, socket.SOCK_STREAM
        )
        self._sock.bind(("127.0.0.1", 0))
        self.ping_error: Exception | None = None
        self.socket_fields: dict[str, int] = {
            "database_connection.fd": self._sock.fileno(),
            "database_connection.local_port": self._sock.getsockname()[1],
        }

    def break_like_pymysql(self, error: Exception | None = None) -> None:
        """Lose the connection: drop the socket, as pymysql's _force_close does.

        With ``error``, the next ping raises it instead of finding a closed
        SQLite database.
        """
        if self._sock is not None:
            self._sock.close()
        self._sock = None
        self.ping_error = error
        super().close()

    @overload
    def cursor(self, factory: None = None) -> sqlite3.Cursor: ...

    @overload
    def cursor(
        self, factory: Callable[[sqlite3.Connection], CursorType]
    ) -> CursorType: ...

    def cursor(
        self, factory: Callable[[sqlite3.Connection], sqlite3.Cursor] | None = None
    ) -> sqlite3.Cursor:
        """Raise the error ``break_like_pymysql`` was given, else open a cursor."""
        if self.ping_error is not None:
            raise self.ping_error
        if factory is None:
            return super().cursor()
        return super().cursor(factory)

    def close(self) -> None:
        """Close the socket, then the SQLite connection."""
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        super().close()


def open_socket_carrying_connection() -> SocketCarryingConnection:
    """Open a new in-memory SQLite database on a socket-carrying connection."""
    return sqlite3.connect(
        ":memory:",
        factory=SocketCarryingConnection,
        check_same_thread=False,
    )


class LostConnectionError(Exception):
    """A driver error whose first argument is the driver's error code."""


class OperationalError(sqlite3.OperationalError):
    """Shaped like pymysql.err.OperationalError: (code, message) arguments.

    It subclasses SQLite's error so that SQLAlchemy's SQLite dialect treats it
    as a DBAPI error, as the MySQL dialect treats pymysql's.
    """


def pymysql_lost_connection_error() -> OperationalError:
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


def lost_connection_error() -> LostConnectionError:
    """Return a driver error caused by a ConnectionResetError, as pymysql raises it."""
    os_error = ConnectionResetError(errno.ECONNRESET, "Connection reset by peer")
    driver_error = LostConnectionError(2013, "Lost connection to MySQL server")
    driver_error.__cause__ = os_error
    return driver_error
