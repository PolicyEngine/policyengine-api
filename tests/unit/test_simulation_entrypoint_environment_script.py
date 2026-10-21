"""Tests for .github/scripts/check_simulation_entrypoint_environment.sh."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github/scripts/check_simulation_entrypoint_environment.sh"
SIMULATION_URL = "https://simulation.example.test"
STAGING_REVISION = "policyengine-simulation-entry-staging-00070-abc"
PRODUCTION_REVISION = "policyengine-simulation-entry-00122-low"
HEALTHY_BODY = '{"status":"healthy"}'


@dataclass(frozen=True)
class FakeCurlReply:
    """What the fake curl prints, and the exit code it returns."""

    output: str
    exit_code: int = 0


# Cloud Run's sample container answers with an HTML page and no revision header.
SAMPLE_CONTAINER_RESPONSE = FakeCurlReply(
    "HTTP/2 200\r\ncontent-type: text/html; charset=utf-8\r\n\r\n<html></html>"
)
# curl --fail exits with 22 when the server answers with an HTTP error.
FAILED_REQUEST = FakeCurlReply("", exit_code=22)


def _entrypoint_response(revision: str) -> FakeCurlReply:
    return FakeCurlReply(
        "HTTP/2 200\r\n"
        "content-type: application/json\r\n"
        f"x-policyengine-simulation-revision: {revision}\r\n"
        "\r\n"
        f"{HEALTHY_BODY}"
    )


def _install_fake_curl(tmp_path: Path, reply: FakeCurlReply) -> Path:
    """Install a fake curl that records its arguments and gives ``reply``."""
    fake_bin_directory = tmp_path / "bin"
    fake_bin_directory.mkdir()
    response_file = tmp_path / "response.txt"
    response_file.write_text(reply.output, encoding="utf-8")
    calls_file = tmp_path / "curl-calls.log"
    fake_curl = fake_bin_directory / "curl"
    fake_curl.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> "{calls_file}"\n'
        f'cat "{response_file}"\n'
        f"exit {reply.exit_code}\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    return fake_bin_directory


def _run_check(
    tmp_path: Path,
    curl_reply: FakeCurlReply,
    *,
    deployment_environment: str,
    sim_entrypoint: str = "cloud_run_simulation_entrypoint",
    simulation_url: str = SIMULATION_URL,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    fake_bin_directory = _install_fake_curl(tmp_path, curl_reply)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO,
        env={
            "PATH": f"{fake_bin_directory}{os.pathsep}{os.environ['PATH']}",
            "DEPLOYMENT_ENVIRONMENT": deployment_environment,
            "SIM_ENTRYPOINT": sim_entrypoint,
            "SIMULATION_ENTRYPOINT_URL": simulation_url,
            "OLD_SIMULATION_GATEWAY_URL": "https://old-gateway.example.test",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    calls_file = tmp_path / "curl-calls.log"
    curl_calls = calls_file.read_text().splitlines() if calls_file.exists() else []
    return result, curl_calls


@pytest.mark.parametrize(
    ("deployment_environment", "revision"),
    [("staging", STAGING_REVISION), ("production", PRODUCTION_REVISION)],
)
def test_accepts_the_simulation_service_of_the_same_environment(
    tmp_path: Path, deployment_environment: str, revision: str
) -> None:
    result, curl_calls = _run_check(
        tmp_path,
        _entrypoint_response(revision),
        deployment_environment=deployment_environment,
    )

    assert result.returncode == 0, result.stderr
    assert len(curl_calls) == 1
    assert curl_calls[0].endswith(f"{SIMULATION_URL}/health")
    assert revision in result.stdout


def test_requests_health_once_without_a_doubled_slash(tmp_path: Path) -> None:
    result, curl_calls = _run_check(
        tmp_path,
        _entrypoint_response(STAGING_REVISION),
        deployment_environment="staging",
        simulation_url=f"{SIMULATION_URL}/",
    )

    assert result.returncode == 0, result.stderr
    assert curl_calls[0].endswith(f" {SIMULATION_URL}/health")


def test_rejects_staging_calling_the_production_simulation_service(
    tmp_path: Path,
) -> None:
    result, _ = _run_check(
        tmp_path,
        _entrypoint_response(PRODUCTION_REVISION),
        deployment_environment="staging",
    )

    assert result.returncode == 1
    assert "it must call policyengine-simulation-entry-staging" in result.stderr
    assert PRODUCTION_REVISION in result.stderr


def test_rejects_production_calling_the_staging_simulation_service(
    tmp_path: Path,
) -> None:
    result, _ = _run_check(
        tmp_path,
        _entrypoint_response(STAGING_REVISION),
        deployment_environment="production",
    )

    assert result.returncode == 1
    assert "it must call policyengine-simulation-entry\n" in result.stderr
    assert STAGING_REVISION in result.stderr


def test_rejects_a_url_that_names_no_entrypoint_revision(tmp_path: Path) -> None:
    result, _ = _run_check(
        tmp_path, SAMPLE_CONTAINER_RESPONSE, deployment_environment="staging"
    )

    assert result.returncode == 1
    assert "did not name a Simulation Entrypoint revision" in result.stderr


def test_rejects_a_revision_name_without_a_cloud_run_suffix(tmp_path: Path) -> None:
    result, _ = _run_check(
        tmp_path,
        _entrypoint_response("policyengine-simulation-entry-staging"),
        deployment_environment="staging",
    )

    assert result.returncode == 1
    assert "is not a Cloud Run revision name" in result.stderr


def test_fails_when_the_health_request_fails(tmp_path: Path) -> None:
    result, curl_calls = _run_check(
        tmp_path, FAILED_REQUEST, deployment_environment="staging"
    )

    assert result.returncode == 22
    assert len(curl_calls) == 1


def test_rejects_an_unknown_deployment_environment(tmp_path: Path) -> None:
    result, curl_calls = _run_check(
        tmp_path,
        _entrypoint_response(STAGING_REVISION),
        deployment_environment="preview",
    )

    assert result.returncode == 2
    assert "DEPLOYMENT_ENVIRONMENT must be staging or production" in result.stderr
    assert curl_calls == []


def test_rejects_a_missing_simulation_url(tmp_path: Path) -> None:
    result, curl_calls = _run_check(
        tmp_path,
        _entrypoint_response(STAGING_REVISION),
        deployment_environment="staging",
        simulation_url="",
    )

    assert result.returncode == 1
    assert "SIMULATION_ENTRYPOINT_URL is required" in result.stderr
    assert curl_calls == []


def test_does_not_check_the_shared_old_gateway(tmp_path: Path) -> None:
    result, curl_calls = _run_check(
        tmp_path,
        _entrypoint_response(PRODUCTION_REVISION),
        deployment_environment="staging",
        sim_entrypoint="old_gateway_direct",
    )

    assert result.returncode == 0, result.stderr
    assert curl_calls == []
    assert "old_gateway_direct" in result.stdout
