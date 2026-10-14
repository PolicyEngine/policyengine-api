"""Characterization tests for the local app boot smoke test."""

import importlib.metadata
import subprocess
import sys
import tempfile
import urllib.error

import pytest

from scripts import smoke_test_local_boot as smoke

PORT = 51234


class _FakeClock:
    """Wall-clock time that only moves when the smoke test sleeps."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _FakeApp:
    """Stands in for the Flask child process and records how it is managed."""

    def __init__(self, *, exits_after_polls=None, ignores_terminate=False):
        self.exits_after_polls = exits_after_polls
        self.ignores_terminate = ignores_terminate
        self.returncode = None
        self.polls = 0
        self.calls: list[tuple] = []
        self.popen_args = None

    def popen(self, command, **kwargs):
        self.popen_args = (command, kwargs)
        kwargs["stdout"].write("app stdout\n")
        kwargs["stderr"].write("app stderr\n")
        return self

    def poll(self):
        self.polls += 1
        if self.exits_after_polls is not None and self.polls > self.exits_after_polls:
            self.returncode = 3
        return self.returncode

    def terminate(self):
        self.calls.append(("terminate",))

    def wait(self, timeout):
        self.calls.append(("wait", timeout))
        if self.ignores_terminate and ("kill",) not in self.calls:
            command_name = "flask"
            raise subprocess.TimeoutExpired(command_name, timeout)
        if self.returncode is None:
            self.returncode = -15
        return self.returncode

    def kill(self):
        self.calls.append(("kill",))


@pytest.fixture
def boot(monkeypatch, tmp_path):
    """Patch the clock, port, version and temp directory; return a runner."""
    clock = _FakeClock()
    monkeypatch.setattr(smoke, "time", clock)
    monkeypatch.setattr(smoke, "find_free_port", lambda: PORT)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "9.9.9")
    monkeypatch.delenv("PYTHONUNBUFFERED", raising=False)

    def run(app, responses):
        fetched = []

        def fake_fetch(url):
            fetched.append(url)
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(smoke.subprocess, "Popen", app.popen)
        monkeypatch.setattr(smoke, "fetch", fake_fetch)
        return smoke.main(), fetched, clock

    return run


def _log_paths(app):
    _command, kwargs = app.popen_args
    return kwargs["stdout"].name, kwargs["stderr"].name


def _header(app):
    stdout_path, stderr_path = _log_paths(app)
    return [
        f"repo: {smoke.REPO_ROOT}",
        f"python: {sys.executable}",
        "policyengine: 9.9.9",
        f"port: {PORT}",
        f"stdout log: {stdout_path}",
        f"stderr log: {stderr_path}",
    ]


CAPTURED_OUTPUT = [
    "",
    "=== stdout ===",
    "app stdout",
    "",
    "=== stderr ===",
    "app stderr",
]
LIVENESS_URL = f"http://127.0.0.1:{PORT}/liveness-check"
READINESS_URL = f"http://127.0.0.1:{PORT}/readiness-check"


def test_boot_passes_when_both_health_checks_answer_ok(boot, capsys):
    app = _FakeApp()

    status, fetched, clock = boot(app, [(200, "OK\n"), (200, "OK\n"), (200, " OK ")])

    assert status == 0
    assert capsys.readouterr().out.splitlines() == [
        *_header(app),
        "",
        "Boot smoke test reached a live app. Probing health endpoints:",
        "/liveness-check: 200 OK",
        "/readiness-check: 200 OK",
        "",
        "Boot smoke test passed.",
    ]
    assert fetched == [LIVENESS_URL, LIVENESS_URL, READINESS_URL]
    assert clock.sleeps == []
    assert app.calls == [("terminate",), ("wait", 5)]
    command, kwargs = app.popen_args
    assert command == [
        sys.executable,
        "-m",
        "flask",
        "--app",
        "policyengine_api.api",
        "run",
        "--without-threads",
        "--no-reload",
        "--port",
        str(PORT),
    ]
    assert kwargs["cwd"] == smoke.REPO_ROOT
    assert kwargs["text"] is True
    assert kwargs["env"]["FLASK_DEBUG"] == "1"
    assert kwargs["env"]["PYTHONUNBUFFERED"] == "1"
    assert kwargs["stdout"].closed
    assert kwargs["stderr"].closed


def test_boot_retries_until_the_app_is_live(boot, capsys):
    app = _FakeApp()

    status, fetched, clock = boot(
        app,
        [
            urllib.error.URLError("refused"),
            TimeoutError(),
            ConnectionError(),
            (503, "starting"),
            (200, "not ok"),
            (200, "OK"),
            (200, "OK"),
            (200, "OK"),
        ],
    )

    assert status == 0
    assert fetched == [LIVENESS_URL] * 6 + [LIVENESS_URL, READINESS_URL]
    assert clock.sleeps == [0.5] * 5
    assert "Boot smoke test passed." in capsys.readouterr().out


def test_boot_fails_when_the_app_exits_before_it_is_live(boot, capsys):
    app = _FakeApp(exits_after_polls=1)

    status, fetched, clock = boot(app, [urllib.error.URLError("refused")])

    assert status == 1
    assert capsys.readouterr().out.splitlines() == [
        *_header(app),
        "",
        "Boot smoke test failed: app did not become ready.",
        *CAPTURED_OUTPUT,
    ]
    assert fetched == [LIVENESS_URL]
    assert clock.sleeps == [0.5]
    assert app.calls == [("wait", 5)]


def test_boot_stops_an_app_that_never_becomes_live(boot, capsys):
    app = _FakeApp()
    responses = [urllib.error.URLError("refused")] * 1200

    status, fetched, clock = boot(app, responses)

    assert status == 1
    assert capsys.readouterr().out.splitlines() == [
        *_header(app),
        "",
        "Boot smoke test failed: app did not become ready.",
        *CAPTURED_OUTPUT,
    ]
    assert len(fetched) == 1200
    assert clock.sleeps == [0.5] * 1200
    assert app.calls == [("terminate",), ("wait", 5)]


def test_boot_fails_when_a_health_probe_is_not_ok(boot, capsys):
    app = _FakeApp()

    status, fetched, _clock = boot(
        app, [(200, "OK"), (200, "OK"), (503, " starting \n")]
    )

    assert status == 1
    assert capsys.readouterr().out.splitlines() == [
        *_header(app),
        "",
        "Boot smoke test reached a live app. Probing health endpoints:",
        "/liveness-check: 200 OK",
        "/readiness-check: 503 starting",
        "",
        "Health endpoint probe failed.",
        *CAPTURED_OUTPUT,
    ]
    assert fetched == [LIVENESS_URL, LIVENESS_URL, READINESS_URL]
    assert app.calls == [("terminate",), ("wait", 5)]


def test_boot_kills_an_app_that_ignores_terminate(boot):
    app = _FakeApp(ignores_terminate=True)

    status, _fetched, _clock = boot(app, [(200, "OK"), (200, "OK"), (200, "OK")])

    assert status == 0
    assert app.calls == [("terminate",), ("wait", 5), ("kill",), ("wait", 5)]


def test_health_probe_errors_propagate_after_stopping_the_app(boot):
    app = _FakeApp()
    error = urllib.error.HTTPError(READINESS_URL, 500, "boom", None, None)

    with pytest.raises(urllib.error.HTTPError):
        boot(app, [(200, "OK"), (200, "OK"), error])

    assert app.calls == [("terminate",), ("wait", 5)]


def test_boot_reports_a_missing_policyengine_package(boot, monkeypatch, capsys):
    def missing(_name):
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", missing)

    boot(_FakeApp(), [(200, "OK"), (200, "OK"), (200, "OK")])

    assert "policyengine: not installed" in capsys.readouterr().out.splitlines()
