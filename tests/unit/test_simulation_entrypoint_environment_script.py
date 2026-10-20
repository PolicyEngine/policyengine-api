"""Tests for .github/scripts/check_simulation_entrypoint_environment.sh."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github/scripts/check_simulation_entrypoint_environment.sh"
PUSH_WORKFLOW = REPO / ".github/workflows/push.yml"
SIMULATION_URL = "https://simulation.example.test"
STAGING_REVISION = "policyengine-simulation-entry-staging-00070-abc"
PRODUCTION_REVISION = "policyengine-simulation-entry-00122-low"
HEALTHY_BODY = '{"status":"healthy"}'
# Cloud Run's placeholder image answers with an HTML page and no revision header.
PLACEHOLDER_RESPONSE = (
    "HTTP/2 200\r\ncontent-type: text/html; charset=utf-8\r\n\r\n<html></html>"
)


def _entrypoint_response(revision: str) -> str:
    return (
        "HTTP/2 200\r\n"
        "content-type: application/json\r\n"
        f"x-policyengine-simulation-revision: {revision}\r\n"
        "\r\n"
        f"{HEALTHY_BODY}"
    )


def _fake_curl(tmp_path: Path, response: str, *, exit_code: int = 0) -> Path:
    """Install a fake curl that records its arguments and prints ``response``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    response_file = tmp_path / "response.txt"
    response_file.write_text(response, encoding="utf-8")
    calls = tmp_path / "curl-calls.log"
    curl = bin_dir / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> "{calls}"\n'
        f'cat "{response_file}"\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return bin_dir


def _run(
    tmp_path: Path,
    response: str,
    *,
    deployment_environment: str,
    sim_entrypoint: str = "cloud_run_simulation_entrypoint",
    curl_exit_code: int = 0,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = _fake_curl(tmp_path, response, exit_code=curl_exit_code)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "DEPLOYMENT_ENVIRONMENT": deployment_environment,
            "SIM_ENTRYPOINT": sim_entrypoint,
            "SIMULATION_ENTRYPOINT_URL": SIMULATION_URL,
            "OLD_SIMULATION_GATEWAY_URL": "https://old-gateway.example.test",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    calls_file = tmp_path / "curl-calls.log"
    calls = calls_file.read_text().splitlines() if calls_file.exists() else []
    return result, calls


@pytest.mark.parametrize(
    ("deployment_environment", "revision"),
    [("staging", STAGING_REVISION), ("production", PRODUCTION_REVISION)],
)
def test_accepts_the_simulation_service_of_the_same_environment(
    tmp_path: Path, deployment_environment: str, revision: str
) -> None:
    result, calls = _run(
        tmp_path,
        _entrypoint_response(revision),
        deployment_environment=deployment_environment,
    )

    assert result.returncode == 0, result.stderr
    assert len(calls) == 1
    assert calls[0].endswith(f"{SIMULATION_URL}/health")
    assert revision in result.stdout


def test_rejects_staging_calling_the_production_simulation_service(
    tmp_path: Path,
) -> None:
    result, _ = _run(
        tmp_path,
        _entrypoint_response(PRODUCTION_REVISION),
        deployment_environment="staging",
    )

    assert result.returncode == 1
    assert "policyengine-simulation-entry-staging" in result.stderr
    assert PRODUCTION_REVISION in result.stderr


def test_rejects_production_calling_the_staging_simulation_service(
    tmp_path: Path,
) -> None:
    result, _ = _run(
        tmp_path,
        _entrypoint_response(STAGING_REVISION),
        deployment_environment="production",
    )

    assert result.returncode == 1
    assert STAGING_REVISION in result.stderr


def test_rejects_a_url_that_names_no_entrypoint_revision(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, PLACEHOLDER_RESPONSE, deployment_environment="staging")

    assert result.returncode == 1
    assert "did not name a Simulation Entrypoint revision" in result.stderr


def test_rejects_a_revision_name_without_a_cloud_run_suffix(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path,
        _entrypoint_response("policyengine-simulation-entry-staging"),
        deployment_environment="staging",
    )

    assert result.returncode == 1
    assert "is not a Cloud Run revision name" in result.stderr


def test_fails_when_the_health_request_fails(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path,
        "",
        deployment_environment="staging",
        curl_exit_code=22,
    )

    assert result.returncode != 0


def test_rejects_an_unknown_deployment_environment(tmp_path: Path) -> None:
    result, calls = _run(
        tmp_path,
        _entrypoint_response(STAGING_REVISION),
        deployment_environment="preview",
    )

    assert result.returncode == 2
    assert "DEPLOYMENT_ENVIRONMENT must be staging or production" in result.stderr
    assert calls == []


def test_does_not_check_the_shared_old_gateway(tmp_path: Path) -> None:
    result, calls = _run(
        tmp_path,
        _entrypoint_response(PRODUCTION_REVISION),
        deployment_environment="staging",
        sim_entrypoint="old_gateway_direct",
    )

    assert result.returncode == 0, result.stderr
    assert calls == []
    assert "old_gateway_direct" in result.stdout


@pytest.mark.parametrize(
    ("job_name", "deployment_environment"),
    [
        ("ensure-staging-model-version-aligns-with-sim-api", "staging"),
        ("ensure-production-model-version-aligns-with-sim-api", "production"),
    ],
)
def test_each_release_checks_its_simulation_service_before_deploying(
    job_name: str, deployment_environment: str
) -> None:
    job = yaml.safe_load(PUSH_WORKFLOW.read_text(encoding="utf-8"))["jobs"][job_name]

    assert job["environment"] == deployment_environment
    assert job["env"]["DEPLOYMENT_ENVIRONMENT"] == deployment_environment
    assert job["env"]["SIM_ENTRYPOINT"] == "${{ vars.SIM_ENTRYPOINT }}"
    assert (
        job["env"]["SIMULATION_ENTRYPOINT_URL"]
        == "${{ secrets.SIMULATION_ENTRYPOINT_URL }}"
    )
    commands = [step.get("run", "") for step in job["steps"]]
    assert "bash .github/scripts/check_simulation_entrypoint_environment.sh" in commands
