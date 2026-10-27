"""Tests for the workflow, its shell wrapper and the script they run."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.unit.telemetry_error_issues.github_support import REPOSITORY
from tests.unit.telemetry_error_issues.report_support import (
    LOG_SOURCE_ENVIRONMENT,
    PROJECT_ID,
)

REPO = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO / ".github" / "scripts" / "sync_telemetry_error_issues.py"
WORKFLOW_PATH = REPO / ".github" / "workflows" / "telemetry-error-issues.yml"
WRAPPER_PATH = REPO / ".github" / "scripts" / "sync_telemetry_error_issues.sh"
WRAPPER_ENVIRONMENT = {
    "GOOGLE_OAUTH_ACCESS_TOKEN": "fake-access-token",
    "GITHUB_TOKEN": "fake-github-token",
    "GITHUB_REPOSITORY": REPOSITORY,
    "TELEMETRY_ERROR_FINGERPRINT_KEY": "f" * 64,
    "OBSERVABILITY_PROJECT_ID": PROJECT_ID,
    **LOG_SOURCE_ENVIRONMENT,
}


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _sync_job() -> dict:
    return _workflow()["jobs"]["sync"]


def _step(name: str) -> dict:
    return next(step for step in _sync_job()["steps"] if step["name"] == name)


def test_workflow_runs_at_00_45_eastern_and_on_request() -> None:
    # PyYAML reads the bare key "on" as the boolean True.
    triggers = _workflow()[True]

    assert triggers["schedule"] == [
        {"cron": "45 0 * * *", "timezone": "America/New_York"}
    ]
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["dry_run"]["type"] == "boolean"
    assert inputs["dry_run"]["default"] is True
    assert inputs["report_date"]["type"] == "string"
    assert inputs["report_date"]["default"] == ""


def test_workflow_job_is_limited_to_master_in_its_environment() -> None:
    workflow = _workflow()
    job = _sync_job()

    assert workflow["concurrency"] == {
        "group": "telemetry-error-issues",
        "cancel-in-progress": False,
    }
    assert job["if"] == "github.repository == 'PolicyEngine/policyengine-api'"
    assert job["environment"] == "telemetry-error-issues"
    assert job["timeout-minutes"] == 15
    assert job["permissions"] == {
        "contents": "read",
        "issues": "write",
        "id-token": "write",
    }
    assert job["steps"][0] == {
        "name": "Require master branch",
        "if": "github.ref != 'refs/heads/master'",
        "run": "exit 1",
    }


def test_workflow_authenticates_as_the_report_service_account() -> None:
    auth = _step("Authenticate to Google Cloud")

    assert auth["id"] == "auth"
    assert auth["uses"] == "google-github-actions/auth@v2"
    assert auth["with"] == {
        "workload_identity_provider": "${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}",
        "service_account": "${{ vars.TELEMETRY_ERROR_ISSUES_SERVICE_ACCOUNT }}",
        "token_format": "access_token",
        "create_credentials_file": False,
    }
    assert _step("Set up Python")["with"] == {"python-version": "3.12"}


def test_workflow_passes_settings_to_the_wrapper() -> None:
    sync = _step("Sync telemetry error issues")

    assert sync["run"] == "bash .github/scripts/sync_telemetry_error_issues.sh"
    assert sync["env"] == {
        "GOOGLE_OAUTH_ACCESS_TOKEN": "${{ steps.auth.outputs.access_token }}",
        "GITHUB_TOKEN": "${{ github.token }}",
        "TELEMETRY_ERROR_FINGERPRINT_KEY": (
            "${{ secrets.TELEMETRY_ERROR_FINGERPRINT_KEY }}"
        ),
        "OBSERVABILITY_PROJECT_ID": "${{ vars.OBSERVABILITY_PROJECT_ID }}",
        "OBSERVABILITY_LOG_BUCKET": "${{ vars.OBSERVABILITY_LOG_BUCKET }}",
        "OBSERVABILITY_LOG_BUCKET_LOCATION": (
            "${{ vars.OBSERVABILITY_LOG_BUCKET_LOCATION }}"
        ),
        "OBSERVABILITY_LOG_DATASET": "${{ vars.OBSERVABILITY_LOG_DATASET }}",
        "OBSERVABILITY_LOG_VIEW": "${{ vars.OBSERVABILITY_LOG_VIEW }}",
        "OBSERVABILITY_SERVICE_NAMESPACE": (
            "${{ vars.OBSERVABILITY_SERVICE_NAMESPACE }}"
        ),
        # A scheduled run has no inputs, so it is never a dry run.
        "DRY_RUN": "${{ github.event_name == 'workflow_dispatch' && inputs.dry_run }}",
        "REPORT_DATE": "${{ inputs.report_date }}",
    }


def _run_wrapper(
    tmp_path: Path, environment: dict[str, str]
) -> tuple[subprocess.CompletedProcess[str], list[str] | None]:
    """Run the wrapper with a fake python3 that records its arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "python-arguments.txt"
    fake_python = bin_dir / "python3"
    fake_python.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{calls}"\n')
    fake_python.chmod(0o755)
    result = subprocess.run(
        ["bash", str(WRAPPER_PATH)],
        cwd=REPO,
        env={"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", **environment},
        text=True,
        capture_output=True,
        check=False,
    )
    arguments = calls.read_text().splitlines() if calls.exists() else None
    return result, arguments


def test_wrapper_passes_bash_syntax_checking() -> None:
    result = subprocess.run(
        ["bash", "-n", str(WRAPPER_PATH)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr


def test_wrapper_runs_the_report_for_the_project(tmp_path: Path) -> None:
    result, arguments = _run_wrapper(tmp_path, WRAPPER_ENVIRONMENT)

    assert result.returncode == 0, result.stderr
    assert arguments == [str(SCRIPT_PATH), "--project-id", PROJECT_ID]


def test_wrapper_masks_the_access_token_and_fingerprint_key(tmp_path: Path) -> None:
    result, _ = _run_wrapper(tmp_path, WRAPPER_ENVIRONMENT)

    assert result.stdout.splitlines() == [
        "::add-mask::fake-access-token",
        f"::add-mask::{'f' * 64}",
    ]


def test_wrapper_adds_dry_run_and_report_date_when_set(tmp_path: Path) -> None:
    environment = {
        **WRAPPER_ENVIRONMENT,
        "DRY_RUN": "true",
        "REPORT_DATE": "2026-10-15",
    }

    result, arguments = _run_wrapper(tmp_path, environment)

    assert result.returncode == 0, result.stderr
    assert arguments == [
        str(SCRIPT_PATH),
        "--project-id",
        PROJECT_ID,
        "--dry-run",
        "--report-date",
        "2026-10-15",
    ]


def test_wrapper_runs_live_when_dry_run_is_false(tmp_path: Path) -> None:
    environment = {**WRAPPER_ENVIRONMENT, "DRY_RUN": "false", "REPORT_DATE": ""}

    _, arguments = _run_wrapper(tmp_path, environment)

    assert arguments == [str(SCRIPT_PATH), "--project-id", PROJECT_ID]


@pytest.mark.parametrize("missing", sorted(WRAPPER_ENVIRONMENT))
def test_wrapper_fails_before_running_when_a_variable_is_missing(
    tmp_path: Path, missing: str
) -> None:
    environment = {
        name: value for name, value in WRAPPER_ENVIRONMENT.items() if name != missing
    }

    result, arguments = _run_wrapper(tmp_path, environment)

    assert result.returncode != 0
    assert f"{missing} is required" in result.stderr
    assert arguments is None
    assert result.stdout == ""


def test_script_imports_its_package_from_another_working_directory(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Report each day's telemetry error groups as GitHub issues." in result.stdout
