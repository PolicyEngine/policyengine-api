"""The Simulation Entrypoint transport's retry, and its record of each attempt.

The first tests use httpx.MockTransport. The last ones send real requests to an
HTTP/1.1 server on 127.0.0.1, so the connection pool, the sockets and
httpcore's trace events are the real ones.
"""

import contextlib
import copy
import datetime
import errno
import ipaddress
import pickle
import socket
import ssl
import struct
import threading
import time
from dataclasses import dataclass
from unittest.mock import patch

import httpcore
import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from policyengine_api.libs import simulation_request_diagnostics
from policyengine_api.libs.gateway_auth import GatewayBearerAuth
from policyengine_api.libs.simulation_entrypoint import SimulationEntrypointClient
from policyengine_api.libs.simulation_entrypoint_transport import (
    SimulationEntrypointConnectionError,
    SimulationEntrypointTransport,
)
from policyengine_api.libs.simulation_request_diagnostics import (
    ConnectionRecord,
    RequestAttempt,
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
def test_get_is_not_retried_after_other_transport_errors(error, runtime):
    service = ScriptedService([error])

    with pytest.raises(SimulationEntrypointConnectionError) as raised:
        service.client().resolve_app_name(
            "us", "1.0.0", policyengine_version=BUNDLE_VERSION
        )

    assert raised.value.__cause__ is error
    assert service.requests == [("GET", "/versions/policyengine")]
    assert service.transports_opened == 1
    [attempt] = runtime.events
    assert attempt["severity"] == "ERROR"
    assert attempt["attributes"]["simulation_request.will_retry"] is False
    assert attempt["attributes"]["simulation_request.outcome"] == "error"
    assert attempt["attributes"]["failure.error_type"] == type(error).__name__


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
        "failure.os_error_type": "BrokenPipeError",
        "failure.os_errno": errno.EPIPE,
        "failure.os_errno_name": "EPIPE",
    }
    # Messages can quote response data, so no record carries one.
    assert not any("message" in key for key in first["attributes"])
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


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadError("[Errno 32] Broken pipe"),
        # httpcore swallows a write error while it sends and reads the
        # response, so a POST can reach the service partly written.
        httpx.WriteError("[Errno 32] Broken pipe"),
        httpx.RemoteProtocolError("Server disconnected without sending a response."),
    ],
    ids=["ReadError", "WriteError", "RemoteProtocolError"],
)
def test_post_is_never_retried(error, runtime):
    service = ScriptedService([error])
    client = service.client()

    with (
        patch(
            "policyengine_api.libs.simulation_entrypoint.validate_worker_spm",
            return_value=None,
        ),
        pytest.raises(type(error)),
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


@dataclass(frozen=True)
class ServerBehavior:
    """How a KeepAliveServer departs from answering every request with 200."""

    reset_request_number: int | None = None
    close_request_number: int | None = None
    ssl_context: ssl.SSLContext | None = None
    plaintext_to_tls: bool = False
    first_answer_delay: float = 0.0
    connections_before_first_answers: int = 1


class KeepAliveServer:
    """An HTTP/1.1 server on 127.0.0.1 that keeps each connection open.

    It answers every request with 200 and ``{}``, except that, when a
    connection's request with number ``reset_request_number`` arrives, it
    resets the connection (a TCP RST, from closing with SO_LINGER 0) instead,
    and when its request with number ``close_request_number`` arrives, it
    closes the connection (a FIN, with no TLS close_notify).

    - ``ssl_context``: serve HTTPS with it.
    - ``plaintext_to_tls``: answer a TLS handshake with plain HTTP and close.
    - ``first_answer_delay``: wait this many seconds before answering each
      connection's first request.
    - ``connections_before_first_answers``: hold each connection's first
      answer until this many connections are open (for at most 5 seconds),
      so that concurrent first requests need that many connections.
    """

    def __init__(self, **behavior):
        self.behavior = ServerBehavior(**behavior)
        self.enough_connections = threading.Event()
        self.stopping = threading.Event()
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.listener.settimeout(0.1)
        scheme = "https" if self.behavior.ssl_context is not None else "http"
        self.base_url = f"{scheme}://127.0.0.1:{self.listener.getsockname()[1]}"
        self.accepted = []
        self.threads = [threading.Thread(target=self._accept, daemon=True)]

    def __enter__(self):
        self.threads[0].start()
        return self

    def __exit__(self, *_exc_info):
        self.stopping.set()
        for sock in (self.listener, *self.accepted):
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
        self.listener.close()
        for thread in self.threads:
            thread.join(timeout=5)
        assert not any(thread.is_alive() for thread in self.threads)

    def _accept(self):
        while not self.stopping.is_set():
            try:
                connection, _address = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            connection.settimeout(None)
            self.accepted.append(connection)
            if len(self.accepted) >= self.behavior.connections_before_first_answers:
                self.enough_connections.set()
            thread = threading.Thread(
                target=self._serve, args=(connection,), daemon=True
            )
            self.threads.append(thread)
            thread.start()

    def _serve(self, connection):
        with contextlib.suppress(OSError), connection:
            if self.behavior.plaintext_to_tls:
                connection.recv(4096)
                connection.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                return
            if self.behavior.ssl_context is not None:
                connection = self.behavior.ssl_context.wrap_socket(
                    connection, server_side=True
                )
            self._answer(connection)

    def _answer(self, connection):
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
                if request_number == self.behavior.reset_request_number:
                    connection.setsockopt(
                        socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                    )
                    return
                if request_number == self.behavior.close_request_number:
                    return
                if request_number == 1:
                    self.enough_connections.wait(timeout=5)
                    time.sleep(self.behavior.first_answer_delay)
                connection.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    b"Content-Length: 2\r\n\r\n{}"
                )


def socket_client(**transport_options):
    return httpx.Client(
        transport=SimulationEntrypointTransport(**transport_options), timeout=5.0
    )


@pytest.fixture(scope="module")
def self_signed_certificate(tmp_path_factory):
    """Return the paths of a certificate and key for 127.0.0.1, signed by itself."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    directory = tmp_path_factory.mktemp("tls")
    certificate_path = directory / "certificate.pem"
    key_path = directory / "key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return certificate_path, key_path


@pytest.mark.timeout(30)
def test_records_a_new_connection_then_its_reuse_with_the_same_socket(runtime):
    # The first answer waits, so the reused connection is much older than its
    # idle time, which runs from the end of that answer.
    with (
        KeepAliveServer(first_answer_delay=0.2) as server,
        socket_client() as client,
    ):
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
    assert new["timing.response_headers_received_ms"] >= 200
    # Plain HTTP has no TLS handshake.
    assert "timing.tls_started_ms" not in new

    assert reused["simulation_request.path"] == "/versions/policyengine"
    assert reused["connection.new"] is False
    assert reused["connection.request_number"] == 2
    assert reused["connection.fd"] == new["connection.fd"]
    assert reused["connection.local_port"] == new["connection.local_port"]
    assert reused["connection.idle_ms"] >= 0
    assert reused["connection.age_ms"] - reused["connection.idle_ms"] >= 200
    assert "timing.connect_started_ms" not in reused
    assert reused["timing.request_sent_ms"] <= reused["timing.response_received_ms"]


def assert_failed_read(failed, connection, *, eof):
    """Check a failed read's record against the connection it was sent on."""
    assert failed["simulation_request.will_retry"] is True
    assert failed["connection.new"] is False
    assert failed["connection.request_number"] == 2
    assert failed["connection.fd"] == connection["connection.fd"]
    assert failed["failure.socket_operation"] == "read"
    assert failed["failure.socket_eof"] is eof
    # The socket was still open when the read failed.
    assert failed["failure.socket_fd"] == connection["connection.fd"]
    assert failed["failure.socket_local_port"] == connection["connection.local_port"]
    assert isinstance(failed["failure.socket_readable"], bool)
    # Reading SO_ERROR would clear another socket's error on a reused fd.
    assert not any("so_error" in key for key in failed)
    assert not any("message" in key for key in failed)
    assert failed["failure.ms_after_request_sent"] == pytest.approx(
        failed["timing.response_headers_failed_ms"] - failed["timing.request_sent_ms"],
        abs=0.002,
    )
    assert (
        failed["failure.ms_after_request_sent"]
        <= failed["simulation_request.duration_ms"]
    )


@pytest.mark.timeout(30)
def test_reused_connection_that_is_reset_is_retried_on_a_new_connection(runtime):
    with KeepAliveServer(reset_request_number=2) as server, socket_client() as client:
        assert client.get(f"{server.base_url}/versions").status_code == 200
        response = client.get(f"{server.base_url}/versions/policyengine")

    assert response.status_code == 200
    assert response.json() == {}
    first, failed, retry = (event["attributes"] for event in runtime.events)

    assert_failed_read(failed, first, eof=False)
    assert failed["failure.error_type"] == "ReadError"
    assert failed["failure.os_error_type"] == "ConnectionResetError"
    assert failed["failure.os_errno"] == errno.ECONNRESET
    assert failed["failure.os_errno_name"] == "ECONNRESET"
    assert failed["failure.socket_os_error_type"] == "ConnectionResetError"
    assert failed["failure.socket_os_errno"] == errno.ECONNRESET
    assert failed["failure.socket_os_errno_name"] == "ECONNRESET"

    assert retry["simulation_request.is_retry"] is True
    assert retry["simulation_request.status_code"] == 200
    assert retry["connection.new"] is True
    assert retry["connection.request_number"] == 1
    assert retry["connection.local_port"] != first["connection.local_port"]


@pytest.mark.timeout(30)
def test_retry_opens_a_new_connection_while_the_pool_holds_another_idle_one(
    runtime,
):
    """The default transport's retry must not take a pooled connection.

    Two concurrent requests leave two idle connections in the pool, and the
    server resets each connection when its second request arrives. A retry
    through the pool would take the other idle connection and be reset too.
    """
    with (
        KeepAliveServer(
            reset_request_number=2, connections_before_first_answers=2
        ) as server,
        socket_client() as client,
    ):
        url = f"{server.base_url}/versions"
        threads = [threading.Thread(target=client.get, args=(url,)) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        response = client.get(f"{server.base_url}/versions/policyengine")

    assert response.status_code == 200
    first_two = [event["attributes"] for event in runtime.events[:2]]
    failed, retry = (event["attributes"] for event in runtime.events[2:])
    pooled_ports = {attributes["connection.local_port"] for attributes in first_two}
    assert len(pooled_ports) == 2
    assert failed["connection.new"] is False
    assert failed["connection.local_port"] in pooled_ports
    assert retry["simulation_request.is_retry"] is True
    assert retry["connection.new"] is True
    assert retry["connection.request_number"] == 1
    assert retry["connection.local_port"] not in pooled_ports


@pytest.mark.timeout(30)
def test_https_connections_are_recorded_and_a_closed_one_retried(
    runtime, self_signed_certificate
):
    certificate_path, key_path = self_signed_certificate
    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_context.load_cert_chain(certificate_path, key_path)
    client_context = ssl.create_default_context(cafile=str(certificate_path))

    with (
        KeepAliveServer(ssl_context=server_context, close_request_number=2) as server,
        socket_client(ssl_context=client_context) as client,
    ):
        assert client.get(f"{server.base_url}/versions").status_code == 200
        response = client.get(f"{server.base_url}/versions/policyengine")

    assert response.status_code == 200
    first, failed, retry = (event["attributes"] for event in runtime.events)
    for new_connection in (first, retry):
        assert new_connection["connection.new"] is True
        assert new_connection["connection.request_number"] == 1
        assert new_connection["connection.fd"] >= 0
        assert new_connection["connection.local_port"] > 0
        tls_steps = [
            new_connection[step]
            for step in (
                "timing.connect_completed_ms",
                "timing.tls_started_ms",
                "timing.tls_completed_ms",
                "timing.headers_sent_ms",
            )
        ]
        assert tls_steps == sorted(tls_steps)
    # The server closed without a TLS close_notify, which reads as the end of
    # the stream, so the connection over TLS is still identified.
    assert_failed_read(failed, first, eof=True)
    assert failed["failure.error_type"] == "RemoteProtocolError"
    assert "timing.tls_started_ms" not in failed
    assert retry["simulation_request.is_retry"] is True
    assert retry["connection.local_port"] != first["connection.local_port"]


class BrokenPipeStream(httpcore.NetworkStream):
    """A connection whose writes fail with EPIPE and whose reads find it closed."""

    def __init__(self):
        self.sockets = socket.socketpair()

    def read(self, max_bytes, timeout=None):
        return b""

    def write(self, buffer, timeout=None):
        os_error = BrokenPipeError(errno.EPIPE, "Broken pipe")
        raise httpcore.WriteError(str(os_error)) from os_error

    def close(self):
        for sock in self.sockets:
            sock.close()

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return self

    def get_extra_info(self, info):
        return self.sockets[0] if info == "socket" else None


class BrokenPipeBackend(httpcore.NetworkBackend):
    """Open only connections whose writes fail, like one the server reset."""

    def connect_tcp(
        self, host, port, timeout=None, local_address=None, socket_options=None
    ):
        return BrokenPipeStream()


def test_failed_header_write_is_recorded_with_its_socket_error(runtime):
    with (
        socket_client(network_backend=BrokenPipeBackend()) as client,
        pytest.raises(httpx.RemoteProtocolError),
    ):
        client.get("http://simulation.example.test/versions")

    failed, retry = (event["attributes"] for event in runtime.events)
    for attempt in (failed, retry):
        # httpcore swallows the write error and reads, which finds the
        # connection closed, so the request fails with RemoteProtocolError.
        assert attempt["failure.error_type"] == "RemoteProtocolError"
        assert "timing.headers_send_failed_ms" in attempt
        assert "timing.headers_sent_ms" not in attempt
        assert "timing.response_headers_failed_ms" in attempt
        assert attempt["failure.socket_operation"] == "write"
        assert attempt["failure.socket_eof"] is False
        assert attempt["failure.socket_os_error_type"] == "BrokenPipeError"
        assert attempt["failure.socket_os_errno"] == errno.EPIPE
        assert attempt["failure.socket_os_errno_name"] == "EPIPE"
        assert attempt["failure.socket_fd"] >= 0
    assert failed["simulation_request.will_retry"] is True
    assert retry["simulation_request.is_retry"] is True


@pytest.mark.timeout(30)
def test_reused_connection_the_server_closes_is_recorded_and_retried(runtime):
    with KeepAliveServer(close_request_number=2) as server, socket_client() as client:
        assert client.get(f"{server.base_url}/versions").status_code == 200
        response = client.get(f"{server.base_url}/versions/policyengine")

    assert response.status_code == 200
    first, failed, retry = (event["attributes"] for event in runtime.events)
    assert failed["simulation_request.will_retry"] is True
    assert failed["failure.error_type"] == "RemoteProtocolError"
    assert "failure.os_error_type" not in failed
    assert failed["failure.socket_operation"] == "read"
    assert failed["failure.socket_eof"] is True
    assert failed["failure.socket_fd"] == first["connection.fd"]
    assert failed["failure.socket_local_port"] == first["connection.local_port"]
    assert retry["simulation_request.is_retry"] is True
    assert retry["connection.new"] is True


@pytest.mark.timeout(30)
def test_failed_tls_handshake_records_the_connections_socket(runtime):
    with KeepAliveServer(plaintext_to_tls=True) as server, socket_client() as client:
        https_url = server.base_url.replace("http://", "https://")
        with pytest.raises(httpx.ConnectError):
            client.get(f"{https_url}/versions")

    [failed] = (event["attributes"] for event in runtime.events)
    assert failed["simulation_request.will_retry"] is False
    assert failed["connection.new"] is True
    # The handshake closed the socket, so these are from when TCP connected.
    assert failed["connection.fd"] >= 0
    assert failed["connection.local_port"] > 0
    assert failed["failure.socket_operation"] == "tls_handshake"
    assert failed["failure.socket_eof"] is False
    assert failed["failure.socket_os_error_type"].startswith("SSL")
    assert "timing.tls_started_ms" in failed
    assert "timing.tls_failed_ms" in failed
    assert "timing.headers_sent_ms" not in failed


@pytest.mark.parametrize(
    ("client_timeout", "retry_timeout"),
    [(30.0, 10.0), (3.0, 3.0), (None, 10.0)],
)
@pytest.mark.usefixtures("runtime")
def test_retry_has_its_own_lower_timeout(client_timeout, retry_timeout):
    timeouts = []

    def handle(request):
        timeouts.append(request.extensions["timeout"])
        if len(timeouts) == 1:
            raise broken_pipe_read_error()
        return httpx.Response(200, json={})

    transport = SimulationEntrypointTransport(
        open_transport=lambda: httpx.MockTransport(handle)
    )
    with httpx.Client(transport=transport, timeout=client_timeout) as client:
        assert client.get(f"{BASE_URL}/versions").status_code == 200

    operations = ("connect", "read", "write", "pool")
    assert timeouts[0] == dict.fromkeys(operations, client_timeout)
    assert timeouts[1] == dict.fromkeys(operations, retry_timeout)


@pytest.mark.usefixtures("runtime")
def test_retry_that_times_out_is_not_retried_again():
    service = ScriptedService([broken_pipe_read_error(), httpx.ReadTimeout("slow")])

    with pytest.raises(SimulationEntrypointConnectionError) as raised:
        service.client().resolve_app_name(
            "us", "1.0.0", policyengine_version=BUNDLE_VERSION
        )

    assert isinstance(raised.value.__cause__, httpx.ReadTimeout)
    assert len(service.requests) == 2


def test_connection_error_can_be_copied_and_pickled():
    error = SimulationEntrypointConnectionError(method="GET", path="/jobs/job-1")
    # pickle and copy both rebuild an exception as cls(*args) from __reduce__.
    error_class, arguments, *_state = error.__reduce__()
    rebuilt_from_reduce = error_class(*arguments)

    assert pickle.dumps(error)
    for rebuilt in (copy.copy(error), copy.deepcopy(error), rebuilt_from_reduce):
        assert type(rebuilt) is SimulationEntrypointConnectionError
        assert (rebuilt.method, rebuilt.path) == ("GET", "/jobs/job-1")
        assert str(rebuilt) == str(error)
    assert str(error) == "No response from the simulation service to GET /jobs/job-1"


def test_last_response_time_is_set_when_the_body_completes():
    """The time is set before httpcore returns the connection to the pool."""
    connection = ConnectionRecord(opened_at=0.0)
    attempt = RequestAttempt(method="GET", path="/versions", number=1)
    attempt.use_connection(connection)

    attempt.on_trace("http11.receive_response_headers.complete", {})
    assert connection.last_response_at is None
    attempt.on_trace("http11.receive_response_body.complete", {})

    assert connection.last_response_at is not None
    assert "timing.response_received_ms" not in attempt.connection_attributes
    assert "response_received" in attempt.step_times


class StaticTokenProvider:
    """Stands in for GatewayAuthTokenProvider with fixed tokens."""

    def __init__(self):
        self.tokens = iter(["first-test-value", "second-test-value"])
        self.current = next(self.tokens)

    def get_token(self):
        return self.current

    def invalidate(self):
        self.current = next(self.tokens)


@pytest.mark.usefixtures("runtime")
def test_retry_leaves_the_callers_request_and_the_auth_resend_unchanged():
    """GatewayBearerAuth resends the request after a 401 with the client's timeouts."""
    sent = []

    def handle(request):
        sent.append(
            (request.extensions["timeout"]["read"], request.headers["Authorization"])
        )
        if len(sent) == 1:
            raise broken_pipe_read_error()
        if len(sent) == 2:
            return httpx.Response(401, json={})
        return httpx.Response(200, json={})

    transport = SimulationEntrypointTransport(
        open_transport=lambda: httpx.MockTransport(handle)
    )
    with httpx.Client(
        transport=transport,
        timeout=30.0,
        auth=GatewayBearerAuth(StaticTokenProvider()),
    ) as client:
        response = client.get(f"{BASE_URL}/versions")

    assert response.status_code == 200
    assert sent == [
        (30.0, "Bearer first-test-value"),
        (10.0, "Bearer first-test-value"),
        (30.0, "Bearer second-test-value"),
    ]
    caller_request = response.request
    assert caller_request.extensions["timeout"] == dict.fromkeys(
        ("connect", "read", "write", "pool"), 30.0
    )
    assert "trace" not in caller_request.extensions
