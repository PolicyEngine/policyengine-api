"""The Simulation Entrypoint transport's retry, and its record of each attempt.

The first tests use httpx.MockTransport. The last ones send real requests to an
HTTP/1.1 server on 127.0.0.1, so the connection pool, the sockets and
httpcore's trace events are the real ones.
"""

import errno
import socket
import struct
import threading
from unittest.mock import patch

import httpx
import pytest

from policyengine_api.libs import simulation_request_diagnostics
from policyengine_api.libs.simulation_entrypoint import SimulationEntrypointClient
from policyengine_api.libs.simulation_entrypoint_transport import (
    SimulationEntrypointConnectionError,
    SimulationEntrypointTransport,
)

BASE_URL = "https://simulation.example.test"
BUNDLE_VERSION = "4.18.3"
APP_NAME = "policyengine-us-test-app"
GATEWAY_AUTH_ENV_VARS = (
    "GATEWAY_AUTH_ISSUER",
    "GATEWAY_AUTH_AUDIENCE",
    "GATEWAY_AUTH_CLIENT_ID",
    "GATEWAY_AUTH_CLIENT_SECRET",
    "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE",
    "GATEWAY_AUTH_REQUIRED",
)


class RecordingRuntime:
    """Stands in for the observability runtime and keeps every event."""

    def __init__(self):
        self.events = []

    def event(self, name, *, severity="INFO", attributes=None):
        self.events.append(
            {"name": name, "severity": severity, "attributes": dict(attributes)}
        )


@pytest.fixture
def runtime(monkeypatch):
    recording_runtime = RecordingRuntime()
    monkeypatch.setattr(
        simulation_request_diagnostics, "get_runtime", lambda: recording_runtime
    )
    return recording_runtime


@pytest.fixture(autouse=True)
def entrypoint_environment(monkeypatch):
    for name in GATEWAY_AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SIM_ENTRYPOINT", "old_gateway_direct")
    monkeypatch.setenv("OLD_SIMULATION_GATEWAY_URL", BASE_URL)


class ScriptedService:
    """A MockTransport handler that raises the scripted errors, then answers 200.

    Every transport the SimulationEntrypointTransport opens is a MockTransport
    with this handler, so ``transports_opened`` counts the pooled transport and
    each retry's own transport.
    """

    def __init__(self, errors=(), *, status_code=200, body=None):
        self.errors = list(errors)
        self.status_code = status_code
        self.body = {"latest": BUNDLE_VERSION, BUNDLE_VERSION: APP_NAME}
        if body is not None:
            self.body = body
        self.requests = []
        self.transports_opened = 0

    def open_transport(self):
        self.transports_opened += 1
        return httpx.MockTransport(self.handle)

    def handle(self, request):
        self.requests.append((request.method, request.url.path))
        if self.errors:
            raise self.errors.pop(0)
        return httpx.Response(self.status_code, json=self.body)

    def client(self):
        return SimulationEntrypointClient(
            transport=SimulationEntrypointTransport(open_transport=self.open_transport)
        )


def broken_pipe_read_error():
    """Return an httpx.ReadError caused by a BrokenPipeError, as httpx raises it."""
    os_error = BrokenPipeError(errno.EPIPE, "Broken pipe")
    read_error = httpx.ReadError(str(os_error))
    read_error.__cause__ = os_error
    return read_error


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadError("[Errno 32] Broken pipe"),
        httpx.WriteError("[Errno 32] Broken pipe"),
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
    ],
    ids=["ReadError", "WriteError", "RemoteProtocolError"],
)
@pytest.mark.usefixtures("runtime")
def test_get_that_breaks_once_is_retried_on_a_new_transport_and_succeeds(error):
    service = ScriptedService([error])

    resolved = service.client().resolve_app_name(
        "us", "1.0.0", policyengine_version=BUNDLE_VERSION
    )

    assert resolved == (APP_NAME, "1.0.0")
    assert service.requests == [("GET", "/versions/policyengine")] * 2
    # The pooled transport, then the retry's own transport.
    assert service.transports_opened == 2


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("timed out"),
        httpx.ConnectError("[Errno 111] Connection refused"),
        httpx.PoolTimeout("timed out"),
    ],
    ids=["ReadTimeout", "ConnectError", "PoolTimeout"],
)
@pytest.mark.usefixtures("runtime")
def test_get_is_not_retried_after_other_transport_errors(error):
    service = ScriptedService([error])

    with pytest.raises(SimulationEntrypointConnectionError) as raised:
        service.client().resolve_app_name(
            "us", "1.0.0", policyengine_version=BUNDLE_VERSION
        )

    assert raised.value.__cause__ is error
    assert service.requests == [("GET", "/versions/policyengine")]
    assert service.transports_opened == 1


@pytest.mark.usefixtures("runtime")
def test_get_is_not_retried_after_an_error_status():
    service = ScriptedService(status_code=503, body={"detail": "unavailable"})

    with pytest.raises(httpx.HTTPStatusError):
        service.client().resolve_app_name(
            "us", "1.0.0", policyengine_version=BUNDLE_VERSION
        )

    assert service.requests == [("GET", "/versions/policyengine")]
    assert service.transports_opened == 1


def test_get_that_breaks_twice_raises_connection_error_and_records_both(runtime):
    first_error = broken_pipe_read_error()
    service = ScriptedService([first_error, httpx.ReadError("Connection reset")])

    with pytest.raises(SimulationEntrypointConnectionError) as raised:
        service.client().resolve_app_name(
            "us", "1.0.0", policyengine_version=BUNDLE_VERSION
        )

    assert raised.value.method == "GET"
    assert raised.value.path == "/versions/policyengine"
    assert isinstance(raised.value.__cause__, httpx.ReadError)
    assert service.requests == [("GET", "/versions/policyengine")] * 2
    first, retry = runtime.events
    assert first["name"] == retry["name"] == "simulation_entrypoint.request"
    assert first["severity"] == "WARNING"
    assert first["attributes"] == {
        **first["attributes"],
        "simulation_request.method": "GET",
        "simulation_request.path": "/versions/policyengine",
        "simulation_request.attempt": 1,
        "simulation_request.is_retry": False,
        "simulation_request.outcome": "error",
        "simulation_request.will_retry": True,
        "failure.error_type": "ReadError",
        "failure.error_message": "[Errno 32] Broken pipe",
        "failure.os_error_type": "BrokenPipeError",
        "failure.os_errno": errno.EPIPE,
        "failure.os_errno_name": "EPIPE",
    }
    assert retry["severity"] == "ERROR"
    assert retry["attributes"]["simulation_request.attempt"] == 2
    assert retry["attributes"]["simulation_request.is_retry"] is True
    assert retry["attributes"]["simulation_request.will_retry"] is False
    assert "failure.os_error_type" not in retry["attributes"]


def test_retry_that_succeeds_is_recorded_as_the_retry(runtime):
    service = ScriptedService([broken_pipe_read_error()])

    service.client().resolve_app_name(
        "us", "1.0.0", policyengine_version=BUNDLE_VERSION
    )

    first, retry = runtime.events
    assert first["attributes"]["simulation_request.will_retry"] is True
    assert retry["severity"] == "INFO"
    assert retry["attributes"] == {
        **retry["attributes"],
        "simulation_request.attempt": 2,
        "simulation_request.is_retry": True,
        "simulation_request.outcome": "response",
        "simulation_request.status_code": 200,
    }
    assert isinstance(retry["attributes"]["simulation_request.duration_ms"], float)
    assert isinstance(retry["attributes"]["simulation_request.started_at"], str)


def test_post_is_never_retried(runtime):
    service = ScriptedService([broken_pipe_read_error()])
    client = service.client()

    with (
        patch(
            "policyengine_api.libs.simulation_entrypoint.validate_worker_spm",
            return_value=None,
        ),
        pytest.raises(httpx.ReadError),
    ):
        client.run({"country": "us", "time_period": "2026"})

    assert service.requests == [("POST", "/simulate/economy/comparison")]
    assert service.transports_opened == 1
    [attempt] = runtime.events
    assert attempt["severity"] == "ERROR"
    assert attempt["attributes"]["simulation_request.method"] == "POST"
    assert attempt["attributes"]["simulation_request.will_retry"] is False


@pytest.mark.parametrize(
    ("method_name", "path"),
    [
        ("get_execution_by_id", "/jobs/job-1"),
        ("get_budget_window_batch_by_id", "/budget-window-jobs/job-1"),
    ],
)
@pytest.mark.usefixtures("runtime")
def test_job_polls_are_retried_once(method_name, path):
    service = ScriptedService([broken_pipe_read_error()], body={"status": "running"})

    execution = getattr(service.client(), method_name)("job-1")

    assert execution.status == "running"
    assert service.requests == [("GET", path)] * 2


def test_runtime_failure_leaves_the_response_unchanged(monkeypatch):
    def failing_runtime():
        msg = "telemetry is down"
        raise RuntimeError(msg)

    monkeypatch.setattr(simulation_request_diagnostics, "get_runtime", failing_runtime)
    service = ScriptedService([broken_pipe_read_error()])

    resolved = service.client().resolve_app_name(
        "us", "1.0.0", policyengine_version=BUNDLE_VERSION
    )

    assert resolved == (APP_NAME, "1.0.0")


class KeepAliveServer:
    """An HTTP/1.1 server on 127.0.0.1 that keeps each connection open.

    It answers every request with 200 and ``{}``, except that, with
    ``reset_request_number``, it resets each connection (a TCP RST, from
    closing with SO_LINGER 0) when that connection's request with that number
    arrives, instead of answering it.
    """

    def __init__(self, reset_request_number=None):
        self.reset_request_number = reset_request_number
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.base_url = f"http://127.0.0.1:{self.listener.getsockname()[1]}"
        self.threads = [threading.Thread(target=self._accept, daemon=True)]

    def __enter__(self):
        self.threads[0].start()
        return self

    def __exit__(self, *_exc_info):
        self.listener.close()

    def _accept(self):
        while True:
            try:
                connection, _address = self.listener.accept()
            except OSError:
                return
            thread = threading.Thread(
                target=self._serve, args=(connection,), daemon=True
            )
            self.threads.append(thread)
            thread.start()

    def _serve(self, connection):
        with connection:
            received = b""
            request_number = 0
            while True:
                while b"\r\n\r\n" not in received:
                    chunk = connection.recv(4096)
                    if not chunk:
                        return
                    received += chunk
                _headers, received = received.split(b"\r\n\r\n", 1)
                request_number += 1
                if request_number == self.reset_request_number:
                    connection.setsockopt(
                        socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                    )
                    return
                connection.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    b"Content-Length: 2\r\n\r\n{}"
                )


def socket_client():
    return httpx.Client(transport=SimulationEntrypointTransport(), timeout=5.0)


@pytest.mark.timeout(30)
def test_records_a_new_connection_then_its_reuse_with_the_same_socket(runtime):
    with KeepAliveServer() as server, socket_client() as client:
        assert client.get(f"{server.base_url}/versions").status_code == 200
        assert client.get(f"{server.base_url}/versions/policyengine").status_code == 200

    new, reused = (event["attributes"] for event in runtime.events)
    assert new["connection.new"] is True
    assert new["connection.request_number"] == 1
    assert new["connection.fd"] >= 0
    assert new["connection.local_port"] > 0
    assert "connection.idle_ms" not in new
    steps = [
        "timing.connect_started_ms",
        "timing.connect_completed_ms",
        "timing.headers_sent_ms",
        "timing.request_sent_ms",
        "timing.response_headers_received_ms",
        "timing.response_received_ms",
    ]
    step_times = [new[step] for step in steps]
    assert step_times == sorted(step_times)
    # Plain HTTP has no TLS handshake.
    assert "timing.tls_started_ms" not in new

    assert reused["simulation_request.path"] == "/versions/policyengine"
    assert reused["connection.new"] is False
    assert reused["connection.request_number"] == 2
    assert reused["connection.fd"] == new["connection.fd"]
    assert reused["connection.local_port"] == new["connection.local_port"]
    assert 0 <= reused["connection.idle_ms"] <= reused["connection.age_ms"]
    assert "timing.connect_started_ms" not in reused
    assert reused["timing.request_sent_ms"] <= reused["timing.response_received_ms"]


@pytest.mark.timeout(30)
def test_reused_connection_that_is_reset_is_retried_on_a_new_connection(runtime):
    with KeepAliveServer(reset_request_number=2) as server, socket_client() as client:
        assert client.get(f"{server.base_url}/versions").status_code == 200
        response = client.get(f"{server.base_url}/versions/policyengine")

    assert response.status_code == 200
    assert response.json() == {}
    first, failed, retry = (event["attributes"] for event in runtime.events)

    assert failed["simulation_request.will_retry"] is True
    assert failed["connection.new"] is False
    assert failed["connection.request_number"] == 2
    assert failed["connection.fd"] == first["connection.fd"]
    assert failed["failure.error_type"] == "ReadError"
    assert failed["failure.os_error_type"] == "ConnectionResetError"
    assert failed["failure.os_errno"] == errno.ECONNRESET
    assert failed["failure.socket_operation"] == "read"
    assert failed["failure.socket_os_errno"] == errno.ECONNRESET
    # The socket was still open when the read failed.
    assert failed["failure.socket_fd"] == first["connection.fd"]
    assert isinstance(failed["failure.socket_so_error"], int)
    assert isinstance(failed["failure.socket_readable"], bool)
    assert failed["failure.ms_after_request_sent"] >= 0
    assert "timing.response_headers_failed_ms" in failed

    assert retry["simulation_request.is_retry"] is True
    assert retry["simulation_request.status_code"] == 200
    assert retry["connection.new"] is True
    assert retry["connection.request_number"] == 1
    assert retry["connection.local_port"] != first["connection.local_port"]
