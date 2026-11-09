"""ERROR records for gunicorn workers that a signal ended (issue #4242).

The first tests run gunicorn as Cloud Run does, with uvicorn workers and the
settings module gcp/cloud_run/start.sh loads, and read the records its main
process writes to standard output. The others call that module's hooks with
stand-ins for gunicorn's main process and worker.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import pytest

from policyengine_api import gunicorn_config

REPO = Path(__file__).resolve().parents[2]
GUNICORN_SETTINGS = "python:policyengine_api.gunicorn_config"
OBSERVABILITY_ENVIRONMENT = {
    "APP_ENVIRONMENT": "production",
    "CLOUD_RUN_REGION": "us-central1",
    "K_REVISION": "policyengine-api-00231-had",
    "OBSERVABILITY_SERVICE_NAMESPACE": "policyengine.api-v1",
    "OBSERVABILITY_TRACE_PROJECT_ID": "trace-project",
}
WAIT_SECONDS = 60

# A stand-in for the API: answers every request, except that /slow writes the
# file SLOW_REQUEST_STARTED names and then waits for a minute.
APPLICATION_SOURCE = """
import asyncio
import os


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope["path"] == "/slow":
        with open(os.environ["SLOW_REQUEST_STARTED"], "w") as marker:
            marker.write("started")
        await asyncio.sleep(60)
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})
"""


def _wait_until(condition, description):
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.05)
    pytest.fail(f"Timed out waiting for {description}")


class GunicornServer:
    """gunicorn with one uvicorn worker, writing its output to files."""

    def __init__(self, directory: Path, *options: str) -> None:
        (directory / "worker_exit_application.py").write_text(
            APPLICATION_SOURCE, encoding="utf-8"
        )
        self.slow_request_started = directory / "slow-request-started"
        self.standard_output = directory / "stdout.log"
        self.standard_error = directory / "stderr.log"
        environment = {
            **os.environ,
            **OBSERVABILITY_ENVIRONMENT,
            "SLOW_REQUEST_STARTED": str(self.slow_request_started),
        }
        with (
            self.standard_output.open("wb") as standard_output,
            self.standard_error.open("wb") as standard_error,
        ):
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "gunicorn",
                    "worker_exit_application:app",
                    "--config",
                    GUNICORN_SETTINGS,
                    "--pythonpath",
                    str(directory),
                    "--worker-class",
                    "uvicorn.workers.UvicornWorker",
                    "--workers",
                    "1",
                    "--bind",
                    "127.0.0.1:0",
                    "--no-control-socket",
                    *options,
                ],
                cwd=REPO,
                env=environment,
                stdout=standard_output,
                stderr=standard_error,
            )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exception: object) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()

    def gunicorn_log(self) -> str:
        return self.standard_error.read_text(encoding="utf-8", errors="replace")

    def booted_worker_pids(self) -> list[int]:
        booted = re.findall(r"Booting worker with pid: (\d+)", self.gunicorn_log())
        return [int(pid) for pid in booted]

    def wait_for_worker(self, number: int) -> int:
        """Return the process ID of the numberth worker the main process started."""
        pids = _wait_until(
            lambda: (
                len(self.booted_worker_pids()) >= number and self.booted_worker_pids()
            ),
            f"worker {number} to boot",
        )
        return pids[number - 1]

    def port(self) -> int:
        listening = _wait_until(
            lambda: re.search(
                r"Listening at: http://127\.0\.0\.1:(\d+)", self.gunicorn_log()
            ),
            "gunicorn to listen",
        )
        return int(listening.group(1))

    def get(self, path: str) -> int:
        def answered() -> int | None:
            connection = http.client.HTTPConnection("127.0.0.1", self.port(), timeout=5)
            try:
                connection.request("GET", path)
                return connection.getresponse().status
            except OSError:
                return None
            finally:
                connection.close()

        return _wait_until(answered, f"an answer to GET {path}")

    def stop(self) -> None:
        """Ask the main process to shut down, as Cloud Run does, and wait for it."""
        self.process.send_signal(signal.SIGTERM)
        self.process.wait(timeout=WAIT_SECONDS)

    def records(self) -> list[dict]:
        records = []
        for text in self.standard_output.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(text)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def error_records(self) -> list[dict]:
        return [
            record
            for record in self.records()
            if record.get("severity") in {"ERROR", "CRITICAL", "ALERT", "EMERGENCY"}
        ]


def test_cloud_run_start_script_loads_the_gunicorn_settings():
    start_script = (REPO / "gcp/cloud_run/start.sh").read_text(encoding="utf-8")

    assert f"--config {GUNICORN_SETTINGS}" in start_script


def test_worker_killed_by_a_signal_writes_one_error_record(tmp_path):
    with GunicornServer(tmp_path) as server:
        killed_pid = server.wait_for_worker(1)
        os.kill(killed_pid, signal.SIGKILL)
        server.wait_for_worker(2)
        server.stop()

        records = server.error_records()

    assert len(records) == 1, records
    record = records[0]
    assert record["message"] == (
        f"Signal SIGKILL ended gunicorn worker process {killed_pid}"
    )
    assert record["attributes"] == {
        "signal": "SIGKILL",
        "signal_number": signal.SIGKILL.value,
        "worker_pid": killed_pid,
    }
    assert record["schema_version"] == "policyengine.observability.v2"
    assert record["service.name"] == "policyengine-api"
    assert record["service.namespace"] == "policyengine.api-v1"
    assert record["deployment.environment.name"] == "production"
    assert record["cloud.region"] == "us-central1"
    assert record["service.instance.id"].startswith("policyengine-api-00231-had:")


def test_worker_recycled_after_its_maximum_requests_writes_no_error_record(tmp_path):
    with GunicornServer(tmp_path, "--max-requests", "1") as server:
        first_pid = server.wait_for_worker(1)
        assert server.get("/") == 200
        second_pid = server.wait_for_worker(2)
        server.stop()

        records = server.error_records()
        gunicorn_log = server.gunicorn_log()

    assert second_pid != first_pid
    assert "Maximum request limit" in gunicorn_log
    assert records == []


def test_worker_the_main_process_kills_while_shutting_down_writes_no_error_record(
    tmp_path,
):
    """A deploy stops a worker that is still serving a request.

    The main process sends SIGTERM, waits out its graceful timeout and then
    sends SIGKILL; it usually exits before reaping the worker, which is why
    the hook tests below also cover a reaped worker.
    """
    with GunicornServer(tmp_path, "--graceful-timeout", "1") as server:
        server.wait_for_worker(1)
        slow_request = threading.Thread(
            target=_send_slow_request, args=(server.port(),), daemon=True
        )
        slow_request.start()
        _wait_until(server.slow_request_started.exists, "the slow request to start")
        stopping_started = time.monotonic()
        server.stop()
        stopping_seconds = time.monotonic() - stopping_started

        records = server.error_records()
        gunicorn_log = server.gunicorn_log()

    assert "Shutting down: Master" in gunicorn_log
    assert stopping_seconds < 30, "the main process did not kill the busy worker"
    assert records == []


def _send_slow_request(port: int) -> None:
    """Send GET /slow once; the main process ends it by killing the worker."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=WAIT_SECONDS)
    with contextlib.suppress(OSError, http.client.HTTPException):
        connection.request("GET", "/slow")
        connection.getresponse()
    connection.close()


def _signal_status(signal_number: int) -> int:
    """Return the wait status of a process a signal ended (POSIX encoding)."""
    return int(signal_number)


def _exit_status(exit_code: int) -> int:
    """Return the wait status of a process that exited with exit_code."""
    return exit_code << 8


class GunicornLog:
    """Keeps the messages the hooks write to gunicorn's error log."""

    def __init__(self) -> None:
        self.exceptions: list[tuple[str, str]] = []

    def exception(self, message: str, *arguments: object) -> None:
        self.exceptions.append((message % arguments, type(sys.exc_info()[1]).__name__))


def _main_process(*, listening: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        pid=os.getpid(),
        LISTENERS=[object()] if listening else [],
        log=GunicornLog(),
    )


def _reap_worker(monkeypatch, main_process, worker_pid: int, status: int) -> None:
    """Start the hooks, then reap one worker exit and report it as gunicorn does."""
    exits = [(worker_pid, status)]
    monkeypatch.setattr(
        os,
        "waitpid",
        lambda _pid, _options: exits.pop(0) if exits else (0, 0),
    )
    gunicorn_config.on_starting(main_process)
    while os.waitpid(-1, os.WNOHANG)[0]:
        continue
    gunicorn_config.child_exit(main_process, SimpleNamespace(pid=worker_pid))


def _written_records(capsys) -> list[dict]:
    return [json.loads(text) for text in capsys.readouterr().out.splitlines()]


@pytest.fixture
def observability_environment(monkeypatch):
    for name, value in OBSERVABILITY_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize(
    "ended_by",
    [signal.SIGKILL, signal.SIGSEGV, signal.SIGABRT, signal.SIGBUS],
)
def test_worker_ended_by_an_unexpected_signal_is_recorded_at_error(
    monkeypatch, capsys, observability_environment, ended_by
):
    _reap_worker(monkeypatch, _main_process(), 4321, _signal_status(ended_by))

    records = _written_records(capsys)

    assert [(record["severity"], record["message"]) for record in records] == [
        ("ERROR", f"Signal {ended_by.name} ended gunicorn worker process 4321")
    ]
    assert records[0]["attributes"] == {
        "signal": ended_by.name,
        "signal_number": ended_by.value,
        "worker_pid": 4321,
    }


@pytest.mark.parametrize("ended_by", [signal.SIGTERM, signal.SIGINT, signal.SIGQUIT])
def test_worker_ended_by_a_stop_signal_writes_no_record(
    monkeypatch, capsys, observability_environment, ended_by
):
    _reap_worker(monkeypatch, _main_process(), 4321, _signal_status(ended_by))

    assert _written_records(capsys) == []


def test_worker_killed_while_the_main_process_stops_writes_no_record(
    monkeypatch, capsys, observability_environment
):
    _reap_worker(
        monkeypatch,
        _main_process(listening=False),
        4321,
        _signal_status(signal.SIGKILL),
    )

    assert _written_records(capsys) == []


@pytest.mark.parametrize("exit_code", [0, 1])
def test_worker_that_exited_with_a_code_writes_no_record(
    monkeypatch, capsys, observability_environment, exit_code
):
    _reap_worker(monkeypatch, _main_process(), 4321, _exit_status(exit_code))

    assert _written_records(capsys) == []


def test_worker_exit_the_hooks_did_not_reap_writes_no_record(
    capsys, observability_environment
):
    gunicorn_config.child_exit(_main_process(), SimpleNamespace(pid=999_999))

    assert _written_records(capsys) == []


def test_failure_to_write_the_record_is_reported_to_gunicorn_log_and_not_raised(
    monkeypatch, capsys, observability_environment
):
    from policyengine_api import gunicorn_worker_exits

    def refuse_configuration(_config):
        message = "observability unavailable"
        raise RuntimeError(message)

    monkeypatch.setattr(gunicorn_worker_exits, "configure", refuse_configuration)
    main_process = _main_process()

    _reap_worker(monkeypatch, main_process, 4321, _signal_status(signal.SIGKILL))

    assert _written_records(capsys) == []
    assert main_process.log.exceptions == [
        ("Could not record how gunicorn worker process 4321 ended", "RuntimeError")
    ]


def test_wait_status_is_kept_only_in_the_main_process(
    monkeypatch, capsys, observability_environment
):
    main_process = _main_process()
    main_process.pid = os.getpid() + 1

    _reap_worker(monkeypatch, main_process, 4321, _signal_status(signal.SIGKILL))

    assert _written_records(capsys) == []


def test_settings_module_leaves_the_application_runtime_unbuilt():
    """Workers fork from the main process, so it must not build the API's runtime.

    A worker that inherited policyengine_api.observability would reuse a
    runtime built in another process instead of building its own.
    """
    script = """
import contextlib
import http.client
import json
import os
import signal
import sys
from types import SimpleNamespace
from typing import Self

from policyengine_api import gunicorn_config

server = SimpleNamespace(pid=os.getpid(), LISTENERS=[object()], log=None)
exits = [(4321, signal.SIGKILL.value)]
os.waitpid = lambda _pid, _options: exits.pop(0) if exits else (0, 0)
gunicorn_config.on_starting(server)
os.waitpid(-1, os.WNOHANG)
gunicorn_config.child_exit(server, SimpleNamespace(pid=4321))
loaded = sorted(
    name
    for name in sys.modules
    if name == "policyengine_api.observability"
    or name.startswith("policyengine_api.observability.")
)
print(json.dumps({"loaded": loaded}), file=sys.stderr)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        env={**os.environ, **OBSERVABILITY_ENVIRONMENT},
        capture_output=True,
        text=True,
        check=False,
        timeout=WAIT_SECONDS,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stderr.splitlines()[-1]) == {"loaded": []}
    assert "Signal SIGKILL ended gunicorn worker process 4321" in result.stdout
