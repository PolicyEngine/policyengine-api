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
