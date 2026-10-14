#!/usr/bin/env python3
"""Boot smoke test for the local PolicyEngine API app.

Starts the real Flask app in debug/local-db mode, waits for it to come up,
hits health endpoints, then shuts it down. If startup fails, prints captured
stdout/stderr to make the failure actionable.
"""

from __future__ import annotations

import importlib.metadata
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
HEALTH_PATHS = ("/liveness-check", "/readiness-check")
BOOT_TIMEOUT_SECONDS = 600
HTTP_TIMEOUT_SECONDS = 2


def _report(message: str) -> None:
    """Print one line of the smoke test's output."""
    print(message)


def find_free_port() -> int:
    """Return a localhost TCP port that was free when checked (nothing reserves it)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def read_text(path: Path) -> str:
    """Return the file's text with undecodable bytes replaced, or "" if missing."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def fetch(url: str) -> tuple[int, str]:
    """Return the status and body of a GET; error statuses raise urllib's HTTPError."""
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        body = response.read().decode("utf-8", errors="replace")
        return response.getcode(), body


def print_section(title: str, body: str) -> None:
    """Print a titled block of captured output, or "(empty)" when there is none."""
    _report(f"\n=== {title} ===")
    _report(body.rstrip() if body else "(empty)")


class _AppLogs(NamedTuple):
    """Where the app's captured stdout and stderr are written."""

    stdout: Path
    stderr: Path


def _log_path(suffix: str) -> Path:
    """Create an empty log file that outlives this script, and return its path."""
    with tempfile.NamedTemporaryFile(
        mode="w+",
        encoding="utf-8",
        delete=False,
        prefix="policyengine-api-boot-",
        suffix=suffix,
    ) as log_file:
        return Path(log_file.name)


def _app_environment() -> dict[str, str]:
    """Return this process's environment with Flask debug mode switched on."""
    env = os.environ.copy()
    env["FLASK_DEBUG"] = "1"
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def _policyengine_version() -> str:
    """Return the installed policyengine version, or "not installed"."""
    try:
        return importlib.metadata.version("policyengine")
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def _start_app(port: int, logs: _AppLogs, env: dict[str, str]) -> subprocess.Popen[str]:
    """Start the Flask app on ``port``, writing its output to ``logs``."""
    with (
        logs.stdout.open("w", encoding="utf-8") as stdout_handle,
        logs.stderr.open("w", encoding="utf-8") as stderr_handle,
    ):
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "flask",
                "--app",
                "policyengine_api.api",
                "run",
                "--without-threads",
                "--no-reload",
                "--port",
                str(port),
            ],
            cwd=REPO_ROOT,
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
        )


def _is_ok(status: int, body: str) -> bool:
    """Whether a health endpoint answered 200 with the body "OK"."""
    return status == HTTPStatus.OK and body.strip() == "OK"


def _wait_until_live(process: subprocess.Popen[str], port: int) -> bool:
    """Poll the liveness check until it passes, the app exits, or time runs out."""
    deadline = time.time() + BOOT_TIMEOUT_SECONDS
    while time.time() < deadline:
        if process.poll() is not None:
            return False

        try:
            status, body = fetch(f"http://127.0.0.1:{port}/liveness-check")
            if _is_ok(status, body):
                return True
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.5)
            continue

        time.sleep(0.5)
    return False


def _stop_unready_app(process: subprocess.Popen[str]) -> None:
    """Reap an app that exited, or stop one that is still starting."""
    if process.poll() is not None:
        process.wait(timeout=5)
    else:
        process.terminate()
    if process.poll() is None:
        process.wait(timeout=5)


def _probe_health(port: int) -> bool:
    """Print each health endpoint's answer, stopping at the first that is not OK."""
    for path in HEALTH_PATHS:
        status, body = fetch(f"http://127.0.0.1:{port}{path}")
        _report(f"{path}: {status} {body.strip()}")
        if not _is_ok(status, body):
            return False
    return True


def _report_failure(message: str, logs: _AppLogs) -> int:
    """Print the failure and the app's captured output, and return exit status 1."""
    _report(message)
    print_section("stdout", read_text(logs.stdout))
    print_section("stderr", read_text(logs.stderr))
    return 1


def _stop_app(process: subprocess.Popen[str]) -> None:
    """Terminate the app if it is still running, killing it if it will not stop."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> int:
    """Boot the Flask app on a free port and return 1 unless both health checks pass.

    On failure print the app's captured stdout and stderr; always stop the app.
    """
    port = find_free_port()
    logs = _AppLogs(stdout=_log_path(".stdout.log"), stderr=_log_path(".stderr.log"))
    env = _app_environment()
    policyengine_version = _policyengine_version()

    _report(f"repo: {REPO_ROOT}")
    _report(f"python: {sys.executable}")
    _report(f"policyengine: {policyengine_version}")
    _report(f"port: {port}")
    _report(f"stdout log: {logs.stdout}")
    _report(f"stderr log: {logs.stderr}")

    process = _start_app(port, logs, env)
    try:
        if not _wait_until_live(process, port):
            _stop_unready_app(process)
            return _report_failure(
                "\nBoot smoke test failed: app did not become ready.", logs
            )

        _report("\nBoot smoke test reached a live app. Probing health endpoints:")
        if not _probe_health(port):
            return _report_failure("\nHealth endpoint probe failed.", logs)

        _report("\nBoot smoke test passed.")
        return 0
    finally:
        _stop_app(process)


if __name__ == "__main__":
    raise SystemExit(main())
