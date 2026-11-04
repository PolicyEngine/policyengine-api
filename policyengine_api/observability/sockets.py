"""Describe sockets and the operating-system errors behind connection failures.

These helpers build attributes for diagnostic records. They never raise: a
socket that is closed, or an object that is not a socket, gives fewer fields.
"""

from __future__ import annotations

import contextlib
import errno
import socket
import ssl
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Mapping

Value = TypeVar("Value")


def socket_identity(sock: socket.socket) -> dict[str, int]:
    """Return a socket's file descriptor and local port.

    The file descriptor is -1 once the socket is closed. The port is left out
    for a socket that is not bound to an IP address, and both are left out
    when the socket cannot be read.
    """
    identity: dict[str, int] = {}
    with contextlib.suppress(Exception):
        identity["fd"] = sock.fileno()
        address = sock.getsockname()
        if isinstance(address, tuple):
            identity["local_port"] = address[1]
    return identity


def pending_socket_error(sock: socket.socket) -> dict[str, int | str]:
    """Return a socket's pending error (``SO_ERROR``) and its errno name.

    Reading ``SO_ERROR`` clears it. Return nothing for a closed socket.
    """
    pending: dict[str, int | str] = {}
    with contextlib.suppress(Exception):
        if sock.fileno() < 0:
            return pending
        code = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        pending["so_error"] = code
        if code:
            pending["so_error_name"] = errno.errorcode.get(code, str(code))
    return pending


def find_os_error(error: BaseException) -> OSError | None:
    """Return the first OSError in ``error``'s cause and context chain.

    httpx and httpcore re-raise socket errors as their own exception types, and
    SQLAlchemy and database drivers wrap them in theirs, so the OSError that
    the socket raised is further down the chain. httpcore's connection pool
    re-raises with ``from None``, which drops the cause but keeps the context,
    so both links are followed.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, OSError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def os_error_attributes(error: BaseException) -> dict[str, int | str]:
    """Return the type, errno and errno name of the OSError behind ``error``.

    For an ``ssl.SSLError`` the errno is OpenSSL's error code, so its name is
    left out and the OpenSSL reason is given instead.
    """
    os_error = find_os_error(error)
    if os_error is None:
        return {}
    attributes: dict[str, int | str] = {"os_error_type": type(os_error).__name__}
    if isinstance(os_error.errno, int):
        attributes["os_errno"] = os_error.errno
        if not isinstance(os_error, ssl.SSLError):
            attributes["os_errno_name"] = errno.errorcode.get(
                os_error.errno, str(os_error.errno)
            )
    reason = getattr(os_error, "reason", None)
    if isinstance(reason, str):
        attributes["os_error_reason"] = reason
    return attributes


def prefixed(prefix: str, attributes: Mapping[str, Value]) -> dict[str, Value]:
    """Return ``attributes`` with ``prefix`` added to every key."""
    return {f"{prefix}{key}": value for key, value in attributes.items()}
