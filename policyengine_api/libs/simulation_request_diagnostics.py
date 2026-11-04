"""Connection diagnostics for each request sent to the Simulation Entrypoint.

Every request the Simulation Entrypoint transport sends, a retry included, is
one attempt, recorded as one ``simulation_entrypoint.request`` event through the
API's observability runtime, so it reaches the same structured log as every
other API record, with the inbound request's ID and trace.

An attempt learns when each step happened from httpcore's trace events (the
httpx ``trace`` request extension), and which connection it used from the
connection's network stream, which binds itself to the current attempt when the
attempt starts TLS, reads or writes on it. A reused connection sends no connect
or TLS trace events, so only the stream can say which connection it was, how
old it is and how long it sat idle.

Recording never changes a request's outcome: it only reads a socket's
identity and readiness, never its pending error, and every step that reads a
socket or emits a record suppresses its own errors. Records carry error types
and errno values, never error messages, which can quote response data.
"""

from __future__ import annotations

import contextlib
import datetime
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from policyengine_api.observability import get_runtime
from policyengine_api.observability.sockets import (
    os_error_attributes,
    prefixed,
    socket_identity,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    import httpcore
    import httpx

REQUEST_EVENT = "simulation_entrypoint.request"
# httpcore emits this when a response body has been read to its end, before the
# connection goes back to the pool for another request to take.
RESPONSE_BODY_COMPLETE = "http11.receive_response_body.complete"

# httpcore trace event -> the step recorded as ``timing.<step>_ms``, the
# milliseconds from the start of the attempt to that event. httpcore names
# events "<logger>.<operation>.<started|complete|failed>".
TRACE_STEPS: Mapping[str, str] = MappingProxyType(
    {
        "connection.connect_tcp.started": "connect_started",
        "connection.connect_tcp.complete": "connect_completed",
        "connection.connect_tcp.failed": "connect_failed",
        "connection.start_tls.started": "tls_started",
        "connection.start_tls.complete": "tls_completed",
        "connection.start_tls.failed": "tls_failed",
        "http11.send_request_headers.complete": "headers_sent",
        "http11.send_request_headers.failed": "headers_send_failed",
        "http11.send_request_body.complete": "request_sent",
        "http11.send_request_body.failed": "request_send_failed",
        "http11.receive_response_headers.complete": "response_headers_received",
        "http11.receive_response_headers.failed": "response_headers_failed",
        RESPONSE_BODY_COMPLETE: "response_received",
        "http11.receive_response_body.failed": "response_read_failed",
    }
)
FAILED_STEPS = tuple(step for step in TRACE_STEPS.values() if step.endswith("_failed"))

_current_attempt: ContextVar[RequestAttempt | None] = ContextVar(
    "simulation_entrypoint_request_attempt", default=None
)


def _milliseconds(seconds: float) -> float:
    return round(seconds * 1_000, 3)


@dataclass
class ConnectionRecord:
    """What the diagnostics know about one connection the pool opened."""

    opened_at: float
    identity: dict[str, int] = field(default_factory=dict)
    requests_started: int = 0
    last_response_at: float | None = None

    @classmethod
    def for_stream(cls, stream: httpcore.NetworkStream) -> ConnectionRecord:
        """Describe a connection that ``stream`` has just opened over TCP."""
        identity: dict[str, int] = {}
        with contextlib.suppress(Exception):
            identity = socket_identity(stream.get_extra_info("socket"))
        return cls(opened_at=time.monotonic(), identity=identity)


@dataclass
class RequestAttempt:
    """One request sent to the Simulation Entrypoint, and how it went."""

    method: str
    path: str
    number: int
    started_at: float = field(default_factory=time.monotonic)
    started_at_utc: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat()
    )
    step_times: dict[str, float] = field(default_factory=dict)
    connection: ConnectionRecord | None = None
    connection_attributes: dict[str, int | float] = field(default_factory=dict)
    socket_failure: dict[str, int | str | bool] = field(default_factory=dict)

    def on_trace(self, event_name: str, _info: Mapping[str, object]) -> None:
        """Note when a step happened; the httpx ``trace`` extension calls this."""
        with contextlib.suppress(Exception):
            step = TRACE_STEPS.get(event_name)
            if step is not None:
                self.step_times.setdefault(step, self._elapsed_ms())
            if event_name == RESPONSE_BODY_COMPLETE and self.connection is not None:
                # Set before httpcore returns the connection to the pool, so the
                # next request on it never reads an older time.
                self.connection.last_response_at = time.monotonic()

    def use_connection(self, connection: ConnectionRecord) -> None:
        """Note the connection this attempt first starts TLS, reads or writes on."""
        with contextlib.suppress(Exception):
            if self.connection is not None:
                return
            now = time.monotonic()
            connection.requests_started += 1
            self.connection = connection
            self.connection_attributes = {
                **prefixed("connection.", connection.identity),
                "connection.request_number": connection.requests_started,
                "connection.age_ms": _milliseconds(now - connection.opened_at),
            }
            if connection.last_response_at is not None:
                self.connection_attributes["connection.idle_ms"] = _milliseconds(
                    now - connection.last_response_at
                )

    def note_socket_failure(
        self,
        stream: httpcore.NetworkStream,
        operation: str,
        error: BaseException | None,
    ) -> None:
        """Note the socket's state when an operation on it first fails.

        ``operation`` is ``read``, ``write`` or ``tls_handshake``. ``error`` is
        None for a read that returned no data (``failure.socket_eof``): the
        server closed or reset the connection. Over TLS the two cannot be told
        apart, because Python's ``ssl`` module turns a reset into the end of the
        stream. This runs before httpcore closes the connection, while the
        socket is still open, except after a failed TLS handshake, which closes
        it; the connection's file descriptor and local port from when it
        connected are recorded separately. Later failures in the same attempt
        keep the first's state.
        """
        with contextlib.suppress(Exception):
            if self.socket_failure:
                return
            failure: dict[str, int | str | bool] = {
                "failure.socket_operation": operation,
                "failure.socket_eof": error is None,
            }
            if error is not None:
                failure.update(prefixed("failure.socket_", os_error_attributes(error)))
            readable = stream.get_extra_info("is_readable")
            if isinstance(readable, bool):
                failure["failure.socket_readable"] = readable
            sock = stream.get_extra_info("socket")
            if sock is not None:
                failure.update(prefixed("failure.socket_", socket_identity(sock)))
            self.socket_failure = failure

    def record_response(self, response: httpx.Response) -> None:
        """Record an attempt that received a complete response."""
        with contextlib.suppress(Exception):
            self._emit(
                "INFO",
                {
                    "simulation_request.outcome": "response",
                    "simulation_request.status_code": response.status_code,
                },
            )

    def record_failure(self, error: BaseException, *, will_retry: bool) -> None:
        """Record an attempt that raised ``error`` instead of returning a response."""
        with contextlib.suppress(Exception):
            failure: dict[str, object] = {
                "simulation_request.outcome": "error",
                "simulation_request.will_retry": will_retry,
                "failure.error_type": type(error).__name__,
                **prefixed("failure.", os_error_attributes(error)),
                **self.socket_failure,
            }
            sent_at = self.step_times.get("request_sent")
            if sent_at is None:
                sent_at = self.step_times.get("headers_sent")
            if sent_at is not None:
                failed_at = max(
                    (
                        self.step_times[step]
                        for step in FAILED_STEPS
                        if step in self.step_times
                    ),
                    default=self._elapsed_ms(),
                )
                failure["failure.ms_after_request_sent"] = round(failed_at - sent_at, 3)
            self._emit("WARNING" if will_retry else "ERROR", failure)

    def _elapsed_ms(self) -> float:
        return _milliseconds(time.monotonic() - self.started_at)

    def _emit(self, severity: str, outcome: Mapping[str, object]) -> None:
        # Recording must never change the request's outcome.
        with contextlib.suppress(Exception):
            attributes: dict[str, object] = {
                "simulation_request.method": self.method,
                "simulation_request.path": self.path,
                "simulation_request.attempt": self.number,
                "simulation_request.is_retry": self.number > 1,
                "simulation_request.started_at": self.started_at_utc,
                "simulation_request.duration_ms": self._elapsed_ms(),
                **self._connection_reuse(),
                **self.connection_attributes,
                **{
                    f"timing.{step}_ms": milliseconds
                    for step, milliseconds in self.step_times.items()
                },
                **outcome,
            }
            get_runtime().event(
                REQUEST_EVENT,
                severity=severity,
                attributes={
                    key: value for key, value in attributes.items() if value is not None
                },
            )

    def _connection_reuse(self) -> dict[str, bool]:
        # httpcore traces connecting only when it opens a connection, so this
        # says whether the attempt tried to open one: it is true for a
        # connection that was refused, which has no file descriptor.
        if "connect_started" in self.step_times:
            return {"connection.new": True}
        if self.connection is not None:
            return {"connection.new": False}
        return {}


@contextlib.contextmanager
def recording(attempt: RequestAttempt) -> Iterator[RequestAttempt]:
    """Make ``attempt`` the one that network streams report to, while in use."""
    token = _current_attempt.set(attempt)
    try:
        yield attempt
    finally:
        _current_attempt.reset(token)


def current_attempt() -> RequestAttempt | None:
    """Return the attempt this thread is sending, if any."""
    return _current_attempt.get()
