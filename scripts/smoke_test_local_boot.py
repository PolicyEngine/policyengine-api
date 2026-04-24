#!/usr/bin/env python3
"""Boot smoke test for the local PolicyEngine API app.

Starts the real Flask app in debug/local-db mode, waits for it to come up,
hits health endpoints, then shuts it down. If startup fails, prints captured
stdout/stderr to make the failure actionable.
"""

from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
HEALTH_PATHS = ("/liveness-check", "/readiness-check")
HTTP_TIMEOUT_SECONDS = 2


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def fetch(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        body = response.read().decode("utf-8", errors="replace")
        return response.getcode(), body


def print_section(title: str, body: str) -> None:
    print(f"\n=== {title} ===")
    print(body.rstrip() if body else "(empty)")


def main() -> int:
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

    print(f"repo: {REPO_ROOT}")
    print(f"python: {sys.executable}")
    print(f"policyengine: {policyengine_version}")
    print(f"port: {port}")
    print(f"stdout log: {stdout_path}")
    print(f"stderr log: {stderr_path}")

    with (
        stdout_path.open("w", encoding="utf-8") as stdout_handle,
        stderr_path.open("w", encoding="utf-8") as stderr_handle,
    ):
        process = subprocess.Popen(
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

    try:
        ready = False
        while True:
            if process.poll() is not None:
                break

            try:
                status, body = fetch(f"http://127.0.0.1:{port}/liveness-check")
                if status == 200 and body.strip() == "OK":
                    ready = True
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(0.5)
                continue

            time.sleep(0.5)

        if not ready:
            process.wait(
                timeout=5
            ) if process.poll() is not None else process.terminate()
            if process.poll() is None:
                process.wait(timeout=5)
            print("\nBoot smoke test failed: app did not become ready.")
            print_section("stdout", read_text(stdout_path))
            print_section("stderr", read_text(stderr_path))
            return 1

        print("\nBoot smoke test reached a live app. Probing health endpoints:")
        for path in HEALTH_PATHS:
            status, body = fetch(f"http://127.0.0.1:{port}{path}")
            print(f"{path}: {status} {body.strip()}")
            if status != 200 or body.strip() != "OK":
                print("\nHealth endpoint probe failed.")
                print_section("stdout", read_text(stdout_path))
                print_section("stderr", read_text(stderr_path))
                return 1

        print("\nBoot smoke test passed.")
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
