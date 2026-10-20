"""Tests for the deploy-pipeline scripts called from .github/workflows/push.yml.

build_changelog.sh, run_release_tests.sh, compute_cloud_run_metadata.sh and
restore_cloud_run_revision.sh replace multi-line run: blocks, so their behaviour
must match what the workflow did inline.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / ".github" / "scripts"


def _recording_command(bin_dir: Path, name: str, log: Path, exit_code: int = 0) -> None:
    command = bin_dir / name
    command.write_text(
        f'#!/usr/bin/env bash\necho "{name} $*" >> "{log}"\nexit {exit_code}\n'
    )
    command.chmod(0o755)


def _run(
    script: str, *args: str, cwd: Path = REPO, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPTS / script), *args],
        cwd=cwd,
        env={
            "HOME": os.environ.get("HOME", ""),
            "PATH": os.environ["PATH"],
            **(env or {}),
        },
        text=True,
        capture_output=True,
        check=False,
    )


def _lines(path: Path) -> list[str]:
    return path.read_text().splitlines() if path.exists() else []


# --- build_changelog.sh ----------------------------------------------------


def _changelog_bin(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python").symlink_to(sys.executable)
    log = tmp_path / "calls.log"
    _recording_command(bin_dir, "towncrier", log)
    return bin_dir, log


def test_build_changelog_uses_the_pyproject_version(tmp_path: Path) -> None:
    bin_dir, log = _changelog_bin(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "3.4.5"\n')

    result = _run(
        "build_changelog.sh",
        cwd=tmp_path,
        env={"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
    )

    assert result.returncode == 0, result.stderr
    assert _lines(log) == ["towncrier build --yes --version 3.4.5"]


def test_build_changelog_fails_without_a_version(tmp_path: Path) -> None:
    bin_dir, log = _changelog_bin(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')

    result = _run(
        "build_changelog.sh",
        cwd=tmp_path,
        env={"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
    )

    assert result.returncode != 0
    assert "no version found" in result.stderr
    assert _lines(log) == []


# --- run_release_tests.sh --------------------------------------------------


def _fake_make(tmp_path: Path, exit_code: int = 0) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env_dump = tmp_path / "env.txt"
    make = bin_dir / "make"
    make.write_text(
        f'#!/usr/bin/env bash\necho "args=$*" > "{env_dump}"\nenv >> "{env_dump}"\nexit {exit_code}\n'
    )
    make.chmod(0o755)
    return bin_dir, env_dump


def test_release_tests_drop_deployment_settings(tmp_path: Path) -> None:
    bin_dir, env_dump = _fake_make(tmp_path)

    result = _run(
        "run_release_tests.sh",
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "ROUTE_IMPL_POLICY": "fastapi_native",
            "DB_WRITE_HOUSEHOLD": "dual",
            "CLOUD_RUN_SERVICE": "policyengine-api-staging",
            "V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE": "projects/x/secrets/y",
            "PUBLIC_API_AUTH_REQUIRED": "1",
            "PUBLIC_API_AUTH_ISSUER": "https://auth.example.test/",
            "PUBLIC_API_AUTH_AUDIENCE": "https://api.policyengine.org/",
            "RUNTIME_CACHE_MODE": "local",
            "RUNTIME_CACHE_URL": "redis://127.0.0.1:6379/0",
        },
    )

    assert result.returncode == 0, result.stderr
    dumped = env_dump.read_text().splitlines()
    assert dumped[0] == "args=test"
    names = {line.split("=", 1)[0] for line in dumped[1:]}
    assert "ROUTE_IMPL_POLICY" not in names
    assert "DB_WRITE_HOUSEHOLD" not in names
    assert "CLOUD_RUN_SERVICE" not in names
    assert "V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE" not in names
    assert "PUBLIC_API_AUTH_REQUIRED" not in names
    assert "PUBLIC_API_AUTH_ISSUER" not in names
    assert "PUBLIC_API_AUTH_AUDIENCE" not in names
    assert "RUNTIME_CACHE_MODE=local" in dumped
    assert "RUNTIME_CACHE_URL=redis://127.0.0.1:6379/0" in dumped


def test_release_tests_fail_when_make_test_fails(tmp_path: Path) -> None:
    bin_dir, _ = _fake_make(tmp_path, exit_code=3)

    result = _run(
        "run_release_tests.sh",
        env={"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
    )

    assert result.returncode == 3


# --- compute_cloud_run_metadata.sh ----------------------------------------

SHA = "0123456789abcdef0123456789abcdef01234567"


def test_metadata_writes_image_and_revision_tags(tmp_path: Path) -> None:
    output = tmp_path / "github_output"

    result = _run(
        "compute_cloud_run_metadata.sh",
        "stage3-prod",
        env={
            "GITHUB_SHA": SHA,
            "GITHUB_RUN_NUMBER": "42",
            "GITHUB_OUTPUT": str(output),
        },
    )

    assert result.returncode == 0, result.stderr
    assert _lines(output) == [
        f"image_tag={SHA}",
        "revision_tag=stage3-prod-42-0123456",
    ]


def test_metadata_staging_tag_stays_short(tmp_path: Path) -> None:
    output = tmp_path / "github_output"

    _run(
        "compute_cloud_run_metadata.sh",
        "stg",
        env={
            "GITHUB_SHA": SHA,
            "GITHUB_RUN_NUMBER": "99999",
            "GITHUB_OUTPUT": str(output),
        },
    )

    tag = _lines(output)[1].split("=", 1)[1]
    assert tag == "stg-99999-0123456"
    assert len(tag) + len("policyengine-api-staging") <= 46


def test_metadata_requires_the_commit_sha(tmp_path: Path) -> None:
    output = tmp_path / "github_output"

    result = _run(
        "compute_cloud_run_metadata.sh",
        "stg",
        env={"GITHUB_RUN_NUMBER": "1", "GITHUB_OUTPUT": str(output)},
    )

    assert result.returncode != 0
    assert "GITHUB_SHA is required" in result.stderr
    assert not output.exists()


# --- restore_cloud_run_revision.sh ----------------------------------------


def _stub_scripts(tmp_path: Path, set_exit: int = 0) -> tuple[Path, Path]:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    log = tmp_path / "calls.log"
    for name, exit_code in (
        ("set_cloud_run_revision.sh", set_exit),
        ("health_check.sh", 0),
    ):
        (scripts / name).write_text(
            f'echo "{name} $* target=${{CLOUD_RUN_TARGET_REVISION:-}}" >> "{log}"\n'
            f"exit {exit_code}\n"
        )
    return scripts, log


def test_restore_rolls_back_then_checks_health(tmp_path: Path) -> None:
    scripts, log = _stub_scripts(tmp_path)

    result = _run(
        "restore_cloud_run_revision.sh",
        "https://stable.example/health",
        env={
            "CLOUD_RUN_SCRIPTS_DIR": str(scripts),
            "CLOUD_RUN_TARGET_REVISION": "rev-1",
        },
    )

    assert result.returncode == 0, result.stderr
    assert _lines(log) == [
        "set_cloud_run_revision.sh  target=rev-1",
        "health_check.sh https://stable.example/health target=rev-1",
    ]


def test_restore_skips_health_check_when_rollback_fails(tmp_path: Path) -> None:
    scripts, log = _stub_scripts(tmp_path, set_exit=1)

    result = _run(
        "restore_cloud_run_revision.sh",
        "https://stable.example/health",
        env={"CLOUD_RUN_SCRIPTS_DIR": str(scripts)},
    )

    assert result.returncode == 1
    assert _lines(log) == ["set_cloud_run_revision.sh  target="]


def test_restore_requires_a_readiness_url(tmp_path: Path) -> None:
    scripts, log = _stub_scripts(tmp_path)

    result = _run(
        "restore_cloud_run_revision.sh", env={"CLOUD_RUN_SCRIPTS_DIR": str(scripts)}
    )

    assert result.returncode != 0
    assert _lines(log) == []
