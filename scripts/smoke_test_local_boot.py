#!/usr/bin/env python3
"""Boot smoke test for the local PolicyEngine API app.

Starts the real ASGI app (the FastAPI routes with the mounted Flask app) in
debug mode, waits until ``/health`` reports ready, then shuts it down. Ready
needs a valid runtime configuration, as on Cloud Run. If startup fails,
prints captured stdout/stderr to make the failure actionable.
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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HEALTH_PATH = "/health"
READY_BODY = '{"status":"healthy"}'
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


def main() -> int:
    """Boot the ASGI app on a free port and return 1 unless /health reports ready.

    On failure print the app's captured stdout and stderr; always stop the app.
    """
    port = find_free_port()
    stdout_file = tempfile.NamedTemporaryFile(
        mode="w+",
        encoding="utf-8",
        delete=False,
        prefix="policyengine-api-boot-",
        suffix=".stdout.log",
    )
    stderr_file = tempfile.NamedTemporaryFile(
        mode="w+",
        encoding="utf-8",
        delete=False,
        prefix="policyengine-api-boot-",
        suffix=".stderr.log",
    )
    stdout_path = Path(stdout_file.name)
    stderr_path = Path(stderr_file.name)
    stdout_file.close()
    stderr_file.close()

    env = os.environ.copy()
    env["FLASK_DEBUG"] = "1"
    env.setdefault("PYTHONUNBUFFERED", "1")

    try:
        policyengine_version = importlib.metadata.version("policyengine")
    except importlib.metadata.PackageNotFoundError:
        policyengine_version = "not installed"

    _report(f"repo: {REPO_ROOT}")
    _report(f"python: {sys.executable}")
    _report(f"policyengine: {policyengine_version}")
    _report(f"port: {port}")
    _report(f"stdout log: {stdout_path}")
    _report(f"stderr log: {stderr_path}")

    with (
        stdout_path.open("w", encoding="utf-8") as stdout_handle,
        stderr_path.open("w", encoding="utf-8") as stderr_handle,
    ):
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "policyengine_api.asgi:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=REPO_ROOT,
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
        )

    try:
        deadline = time.time() + BOOT_TIMEOUT_SECONDS
        ready = False
        last_health = "no response"
        while time.time() < deadline:
            if process.poll() is not None:
                break

            try:
                status, body = fetch(f"http://127.0.0.1:{port}{HEALTH_PATH}")
                last_health = f"{status} {body.strip()}"
                if status == 200 and body.strip() == READY_BODY:
                    ready = True
                    break
            except urllib.error.HTTPError as error:
                # 503 means the app is up but not ready yet.
                last_health = f"{error.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                pass

            time.sleep(0.5)

        if not ready:
            process.wait(
                timeout=5
            ) if process.poll() is not None else process.terminate()
            if process.poll() is None:
                process.wait(timeout=5)
            _report(
                "\nBoot smoke test failed: app did not report ready "
                f"(last {HEALTH_PATH} result: {last_health})."
            )
            print_section("stdout", read_text(stdout_path))
            print_section("stderr", read_text(stderr_path))
            return 1

        _report(f"\n{HEALTH_PATH}: {last_health}")
        _report("\nBoot smoke test passed.")
        return 0
    finally:
        if "process" in locals() and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
