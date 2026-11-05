"""HTTP transport for the Simulation Entrypoint client.

``SimulationEntrypointTransport`` sends each request through httpx's HTTP
transport and records each attempt (``simulation_request_diagnostics``). A GET
that fails because its connection broke (``httpx.ReadError``, ``WriteError`` or
``RemoteProtocolError``) is sent once more, on a new connection. Nothing else is
retried: not a POST, which may have reached the service and submitted a job
before the connection broke; not a timeout; and not an HTTP error status.
``httpx.HTTPTransport(retries=...)`` retries only opening a connection, so it
does not cover a connection that breaks after the request is sent.

The retry's connect, read, write and pool timeouts are each at most
``RETRY_TIMEOUT_SECONDS`` (10 s), or the request's own if that is lower, so a
retry adds at most that much per operation to a request that already failed.
A retry that times out is not retried again.

httpcore 1.0.9 closes a connection whose request raised: on any exception,
``HTTP11Connection.handle_request`` calls ``_response_closed``, which closes the
connection unless both sides finished the exchange, and the connection pool
removes closed connections before it assigns the next request. The failed
connection is therefore never reused. The pool could still give the retry
another idle connection, so the retry goes through a separate transport, which
has to open a new one, and that transport is closed once the response is read.

Because httpx.Client is given this transport, it does not read the
``HTTP_PROXY``, ``HTTPS_PROXY``, ``ALL_PROXY`` or ``NO_PROXY`` environment
variables for this client (httpx builds proxy transports from them only when it
builds its own transport). No proxy variable is set where the API runs.
"""

from __future__ import annotations

import contextlib
import datetime
import functools
import time
from typing import TYPE_CHECKING

import httpcore
import httpx
from typing_extensions import override

from policyengine_api.libs.simulation_request_diagnostics import (
    ConnectionRecord,
    RequestAttempt,
    current_attempt,
    recording,
)

if TYPE_CHECKING:
    import ssl
    from collections.abc import Callable, Iterable

    SocketOption = (
        tuple[int, int, int]
        | tuple[int, int, bytes | bytearray]
        | tuple[int, int, None, int]
    )

RETRYABLE_GET_ERRORS = (httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError)
RETRY_TIMEOUT_SECONDS = 10.0
# The limits httpx.Client uses when it is given none.
DEFAULT_LIMITS = httpx.Limits(
    max_connections=100, max_keepalive_connections=20, keepalive_expiry=5.0
)


class SimulationEntrypointConnectionError(Exception):
    """A read-only request to the simulation service got no HTTP response.

    The transport has already retried the request once where that is allowed.
    The economy routes answer this with 502.
    """

    def __init__(self, method: str, path: str) -> None:
        """Name the request that got no response."""
        self.method = method
        self.path = path
        # The arguments, in order, so copy and pickle can rebuild the error.
        super().__init__(method, path)

    @override
    def __str__(self) -> str:
        return f"No response from the simulation service to {self.method} {self.path}"


class _TrackedNetworkStream(httpcore.NetworkStream):
    """A connection's network stream, which reports its I/O to the current attempt."""

    def __init__(
        self, stream: httpcore.NetworkStream, connection: ConnectionRecord
    ) -> None:
        self._stream = stream
        self._connection = connection

    @override
    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        attempt = current_attempt()
        if attempt is not None:
            attempt.use_connection(self._connection)
        try:
            data = self._stream.read(max_bytes, timeout)
        except Exception as error:
            if attempt is not None:
                attempt.note_socket_failure(self._stream, "read", error)
            raise
        if not data and attempt is not None:
            # The server closed or reset the connection (over TLS the two read
            # the same); h11 raises RemoteProtocolError if a response was due.
            attempt.note_socket_failure(self._stream, "read", None)
        return data

    @override
    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        attempt = current_attempt()
        if attempt is not None:
            attempt.use_connection(self._connection)
        try:
            self._stream.write(buffer, timeout)
        except Exception as error:
            if attempt is not None:
                attempt.note_socket_failure(self._stream, "write", error)
            raise

    @override
    def close(self) -> None:
        self._stream.close()

    @override
    def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.NetworkStream:
        attempt = current_attempt()
        if attempt is not None:
            attempt.use_connection(self._connection)
        try:
            tls_stream = self._stream.start_tls(ssl_context, server_hostname, timeout)
        except Exception as error:
            if attempt is not None:
                attempt.note_socket_failure(self._stream, "tls_handshake", error)
            raise
        return _TrackedNetworkStream(tls_stream, self._connection)

    @override
    def get_extra_info(self, info: str) -> object:
        return self._stream.get_extra_info(info)


class _TrackedNetworkBackend(httpcore.NetworkBackend):
    """Open connections through ``backend``, each with a ConnectionRecord."""

    def __init__(self, backend: httpcore.NetworkBackend) -> None:
        self._backend = backend

    @override
    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SocketOption] | None = None,
    ) -> httpcore.NetworkStream:
        stream = self._backend.connect_tcp(
            host,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )
        return _TrackedNetworkStream(stream, ConnectionRecord.for_stream(stream))

    @override
    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[SocketOption] | None = None,
    ) -> httpcore.NetworkStream:
        stream = self._backend.connect_unix_socket(
            path, timeout=timeout, socket_options=socket_options
        )
        return _TrackedNetworkStream(stream, ConnectionRecord.for_stream(stream))

    @override
    def sleep(self, seconds: float) -> None:
        self._backend.sleep(seconds)


class _TrackedHTTPTransport(httpx.HTTPTransport):
    """httpx's HTTP transport, with a pool that opens connections through a backend."""

    def __init__(
        self,
        ssl_context: ssl.SSLContext,
        network_backend: httpcore.NetworkBackend,
        limits: httpx.Limits = DEFAULT_LIMITS,
    ) -> None:
        super().__init__(verify=ssl_context, limits=limits)
        # httpx.HTTPTransport takes no network backend, so replace the pool it
        # built with one that has the same settings and the tracked backend.
        self._pool = httpcore.ConnectionPool(
            ssl_context=ssl_context,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            network_backend=_TrackedNetworkBackend(network_backend),
        )


def _new_tracked_transport(
    ssl_context: ssl.SSLContext, network_backend: httpcore.NetworkBackend
) -> httpx.BaseTransport:
    return _TrackedHTTPTransport(ssl_context, network_backend)


def _retry_timeouts(timeouts: object) -> dict[str, float]:
    """Return the retry's timeouts: the request's, each at most 10 s."""
    original = timeouts if isinstance(timeouts, dict) else {}
    retry_timeouts = {}
    for operation in ("connect", "read", "write", "pool"):
        seconds = original.get(operation)
        retry_timeouts[operation] = (
            RETRY_TIMEOUT_SECONDS
            if seconds is None
            else min(seconds, RETRY_TIMEOUT_SECONDS)
        )
    return retry_timeouts


class SimulationEntrypointTransport(httpx.BaseTransport):
    """Send Simulation Entrypoint requests, retrying a GET once on a new connection."""

    def __init__(
        self,
        *,
        open_transport: Callable[[], httpx.BaseTransport] | None = None,
        ssl_context: ssl.SSLContext | None = None,
        network_backend: httpcore.NetworkBackend | None = None,
    ) -> None:
        """Send through a pooled transport from ``open_transport``.

        By default that is httpx's HTTP transport with the default limits, with
        every connection tracked for the diagnostics. Its TLS settings are
        ``ssl_context`` (default: httpx's, which verifies certificates against
        certifi), and it opens connections through ``network_backend``
        (default: httpcore's socket backend). Each retry gets a transport of its
        own from ``open_transport``.
        """
        if open_transport is None:
            open_transport = functools.partial(
                _new_tracked_transport,
                ssl_context or httpx.create_ssl_context(),
                network_backend or httpcore.SyncBackend(),
            )
        self._open_transport = open_transport
        self._transport = open_transport()

    @override
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        retry_follows = request.method == "GET"
        try:
            return self._send_attempt(
                self._transport, request, number=1, retry_follows=retry_follows
            )
        except RETRYABLE_GET_ERRORS:
            if not retry_follows:
                raise
        with self._open_transport() as retry_transport:
            return self._send_attempt(
                retry_transport,
                request,
                number=2,
                retry_follows=False,
                timeouts=_retry_timeouts(request.extensions.get("timeout")),
            )

    @override
    def close(self) -> None:
        self._transport.close()

    @staticmethod
    def _send_attempt(
        transport: httpx.BaseTransport,
        request: httpx.Request,
        *,
        number: int,
        retry_follows: bool,
        timeouts: dict[str, float] | None = None,
    ) -> httpx.Response:
        """Send a copy of ``request`` once and read the whole response.

        The copy carries this attempt's trace callback and, for a retry, its
        lower ``timeouts``. ``request`` itself is left unchanged, because the
        client's auth flow may send it again (GatewayBearerAuth resends it
        after a 401), and that send must have the client's own timeouts. The
        body is read here so that a connection that breaks while the body
        arrives is retried and recorded like one that breaks before the headers.
        """
        attempt = RequestAttempt(
            method=request.method, path=request.url.path, number=number
        )
        extensions = {**request.extensions, "trace": attempt.on_trace}
        if timeouts is not None:
            extensions["timeout"] = timeouts
        attempt_request = httpx.Request(
            request.method,
            request.url,
            headers=request.headers,
            stream=request.stream,
            extensions=extensions,
        )
        started_at = time.perf_counter()
        with recording(attempt):
            try:
                response = transport.handle_request(attempt_request)
                try:
                    response.read()
                except BaseException:
                    response.close()
                    raise
            except Exception as error:
                attempt.record_failure(
                    error,
                    will_retry=retry_follows
                    and isinstance(error, RETRYABLE_GET_ERRORS),
                )
                raise
        # httpx sets elapsed when a client closes the response stream, which it
        # does not do for a response that is already read.
        with contextlib.suppress(Exception):
            response.elapsed = datetime.timedelta(
                seconds=time.perf_counter() - started_at
            )
        attempt.record_response(response)
        return response
