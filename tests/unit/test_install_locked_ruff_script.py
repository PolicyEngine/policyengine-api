"""Tests for .github/scripts/install_locked_ruff.sh."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github/scripts/install_locked_ruff.sh"


def _fake_commands(tmp_path: Path, *, pip_exit: int = 0) -> tuple[Path, Path]:
    """Fake pip and ruff that record their arguments instead of installing."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    for name, exit_code in (("pip", pip_exit), ("ruff", 0)):
        command = bin_dir / name
        command.write_text(
            f'#!/usr/bin/env bash\necho "{name} $*" >> "{calls}"\nexit {exit_code}\n'
        )
        command.chmod(0o755)
    return bin_dir, calls


def _run(
    tmp_path: Path, *args: str, pip_exit: int = 0
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir, calls = _fake_commands(tmp_path, pip_exit=pip_exit)
    result = subprocess.run(  # noqa: S603  # runs this repository's script with test-chosen arguments
        ["bash", str(SCRIPT), *args],  # noqa: S607  # bash comes from the test environment's PATH
        cwd=REPO,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "PYTHON": sys.executable,
        },
        text=True,
        capture_output=True,
        check=False,
    )
    logged = calls.read_text().splitlines() if calls.exists() else []
    return result, logged


def _lock(tmp_path: Path, packages: str) -> Path:
    lock = tmp_path / "uv.lock"
    lock.write_text(f"version = 1\n{packages}")
    return lock


def test_installs_the_ruff_version_pinned_in_the_lock(tmp_path: Path) -> None:
    lock = _lock(
        tmp_path,
        '[[package]]\nname = "pytest"\nversion = "8.0.0"\n\n'
        '[[package]]\nname = "ruff"\nversion = "0.15.12"\n',
    )

    result, calls = _run(tmp_path, str(lock))

    assert result.returncode == 0, result.stderr
    assert calls == ["pip install ruff==0.15.12", "ruff --version"]


def test_defaults_to_the_repository_lock(tmp_path: Path) -> None:
    with (REPO / "uv.lock").open("rb") as lock:
        packages = tomllib.load(lock)["package"]
    locked = next(p["version"] for p in packages if p["name"] == "ruff")

    result, calls = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert calls[0] == f"pip install ruff=={locked}"


def test_fails_without_installing_when_ruff_is_not_locked(tmp_path: Path) -> None:
    lock = _lock(tmp_path, '[[package]]\nname = "pytest"\nversion = "8.0.0"\n')

    result, calls = _run(tmp_path, str(lock))

    assert result.returncode != 0
    assert "ruff is not pinned" in result.stderr
    assert calls == []


def test_stops_when_pip_fails(tmp_path: Path) -> None:
    lock = _lock(tmp_path, '[[package]]\nname = "ruff"\nversion = "0.15.12"\n')

    result, calls = _run(tmp_path, str(lock), pip_exit=1)

    assert result.returncode != 0
    assert calls == ["pip install ruff==0.15.12"]
