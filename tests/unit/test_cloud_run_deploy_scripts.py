"""The Cloud Run startup script, images and the simulation version check."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys

import pytest

from tests.unit.cloud_run_deploy_support import (
    REPO,
)
from tests.unit.cloud_run_deploy_support import (
    run_bash as _run_bash,
)
from tests.unit.cloud_run_deploy_support import (
    script_env as _script_env,
)


def _run_simulation_version_guard(
    versions_response: dict,
    *args: str,
    entrypoint: str = "old_gateway_direct",
) -> subprocess.CompletedProcess[str]:
    versions_json = json.dumps(versions_response)
    command = (
        "curl() { printf '%s' "
        f"{shlex.quote(versions_json)}"
        '; }; . .github/request-simulation-model-versions.sh "$@"'
    )
    return _run_bash(
        "-c",
        command,
        "request-simulation-model-versions.sh",
        *args,
        env=_script_env(
            SIM_ENTRYPOINT=entrypoint,
            SIMULATION_ENTRYPOINT_URL="https://simulation.example.test",
            OLD_SIMULATION_GATEWAY_URL="https://old-gateway.example.test",
        ),
    )


def test_cloud_run_startup_uses_asgi_entrypoint():
    start_script = (REPO / "gcp/cloud_run/start.sh").read_text(encoding="utf-8")

    assert "policyengine_api.asgi:app" in start_script
    assert "policyengine_api.api" not in start_script


def test_cloud_run_startup_script_is_shell_syntax_valid():
    result = _run_bash("-n", "gcp/cloud_run/start.sh")

    assert result.returncode == 0, result.stderr


def test_simulation_version_guard_accepts_bundle_and_compatible_country_routes():
    result = _run_simulation_version_guard(
        {
            "policyengine": {
                "latest": "4.18.3",
                "4.18.3": "policyengine-simulation-py4-18-3",
            },
            "us": {
                "latest": "1.729.0",
                "1.729.0": "policyengine-simulation-py4-18-3",
            },
            "uk": {
                "latest": "2.89.2",
                "2.89.2": "policyengine-simulation-py4-18-3",
            },
        },
        "-py",
        "4.18.3",
        "-us",
        "1.729.0",
        "-uk",
        "2.89.2",
    )

    assert result.returncode == 0, result.stderr
    assert "SUCCESS: PolicyEngine bundle route is deployed and ready" in result.stdout


def test_simulation_version_guard_accepts_policyengine_bundle_route_only():
    result = _run_simulation_version_guard(
        {
            "policyengine": {
                "latest": "4.18.5",
                "4.18.5": "policyengine-simulation-py4-18-5",
            },
            "us": {},
            "uk": {},
        },
        "-py",
        "4.18.5",
    )

    assert result.returncode == 0, result.stderr
    assert "PolicyEngine .py bundle 4.18.5 is deployed" in result.stdout
    assert "SUCCESS: PolicyEngine bundle route is deployed and ready" in result.stdout


@pytest.mark.parametrize(
    ("entrypoint", "expected_url"),
    [
        ("old_gateway_direct", "https://old-gateway.example.test"),
        (
            "cloud_run_simulation_entrypoint",
            "https://simulation.example.test",
        ),
    ],
)
def test_simulation_version_guard_uses_selected_endpoint(entrypoint, expected_url):
    result = _run_simulation_version_guard(
        {
            "policyengine": {
                "4.18.5": "policyengine-simulation-py4-18-5",
            },
        },
        "-py",
        "4.18.5",
        entrypoint=entrypoint,
    )

    assert result.returncode == 0, result.stderr
    assert f"Gateway: {expected_url}" in result.stdout


@pytest.mark.parametrize(
    ("entrypoint", "missing_url"),
    [
        ("old_gateway_direct", "OLD_SIMULATION_GATEWAY_URL"),
        ("cloud_run_simulation_entrypoint", "SIMULATION_ENTRYPOINT_URL"),
    ],
)
def test_simulation_version_guard_rejects_missing_selected_endpoint(
    entrypoint,
    missing_url,
):
    command = (
        "curl() { printf '{}'; }; . .github/request-simulation-model-versions.sh \"$@\""
    )
    result = _run_bash(
        "-c",
        command,
        "request-simulation-model-versions.sh",
        "-py",
        "1.0",
        env=_script_env(SIM_ENTRYPOINT=entrypoint),
    )

    assert result.returncode == 1
    assert (
        f"{missing_url} is required when SIM_ENTRYPOINT={entrypoint}" in result.stderr
    )


def test_policyengine_bundle_support_check_passes_pyproject_pin_to_guard(tmp_path):
    capture_path = tmp_path / "guard-args.txt"
    guard_script = tmp_path / "request-simulation-model-versions.sh"
    guard_script.write_text(
        'printf "%s\\n" "$@" > "$CAPTURE_PATH"\n',
        encoding="utf-8",
    )

    result = _run_bash(
        ".github/check-policyengine-bundle-supported.sh",
        env=_script_env(
            SIMULATION_VERSION_GUARD_SCRIPT=str(guard_script),
            CAPTURE_PATH=str(capture_path),
        ),
    )

    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    current_version = re.search(r"policyengine\[models\]==([0-9.]+)", pyproject).group(
        1
    )

    assert result.returncode == 0, result.stderr
    assert capture_path.read_text(encoding="utf-8").splitlines() == [
        "-py",
        current_version,
        "--check-installed-spm",
    ]


def test_simulation_version_guard_rejects_country_route_to_different_app():
    result = _run_simulation_version_guard(
        {
            "policyengine": {
                "latest": "4.18.3",
                "4.18.3": "policyengine-simulation-py4-18-3",
            },
            "us": {
                "latest": "1.729.0",
                "1.729.0": "policyengine-simulation-us1-729-0",
            },
        },
        "-py",
        "4.18.3",
        "-us",
        "1.729.0",
    )

    assert result.returncode == 1
    assert "resolves to policyengine-simulation-us1-729-0" in result.stdout
    assert "not bundle app policyengine-simulation-py4-18-3" in result.stdout


def test_cloud_run_dockerfile_runs_startup_with_bash():
    dockerfile = (REPO / "gcp/cloud_run/Dockerfile").read_text(encoding="utf-8")

    assert 'CMD ["/bin/bash", "/app/start.sh"]' in dockerfile
    assert 'CMD ["/bin/sh", "/app/start.sh"]' not in dockerfile


def test_cloud_run_dockerfile_installs_the_frozen_uv_environment():
    dockerfile = (REPO / "gcp/cloud_run/Dockerfile").read_text(encoding="utf-8")
    dockerignore = (REPO / "gcp/cloud_run/Dockerfile.dockerignore").read_text(
        encoding="utf-8"
    )

    assert "COPY --from=ghcr.io/astral-sh/uv:" in dockerfile
    assert "UV_PROJECT_ENVIRONMENT=/opt/venv" in dockerfile
    assert 'PATH="/opt/venv/bin:${PATH}"' in dockerfile
    assert "COPY pyproject.toml uv.lock README.md ./" in dockerfile
    assert "uv sync --frozen --no-dev --no-editable" in dockerfile
    assert "pip install" not in dockerfile
    assert "!uv.lock" in dockerignore


def test_active_images_install_the_same_policyengine_models_bundle():
    """Both deployed images use the wrapper's exact certified package set."""
    import tomllib

    project = tomllib.loads((REPO / "pyproject.toml").read_text())
    dependencies = project["project"]["dependencies"]
    generic_image = (REPO / "docker/Dockerfile").read_text()
    bundle_pin = next(
        requirement
        for requirement in dependencies
        if requirement.startswith("policyengine[models]==")
    )
    assert bundle_pin in generic_image
    assert not any(item.startswith("spm-calculator") for item in dependencies)
    assert "spm-calculator==" not in generic_image
    for package in ("policyengine-core", "policyengine-us", "policyengine-uk"):
        assert not any(item.startswith(package) for item in dependencies)
        assert f"{package}==" not in generic_image


def test_deployed_startup_execs_only_the_api_server():
    start_script = (REPO / "gcp/cloud_run/start.sh").read_text(encoding="utf-8")

    assert "exec gunicorn" in start_script
    assert "redis-server" not in start_script
    assert "redis-cli" not in start_script
    assert "CACHE_REDIS_HOST" not in start_script
    assert "CACHE_REDIS_PORT" not in start_script
    assert "CACHE_REDIS_DB" not in start_script
    assert "wait" not in start_script
    assert "pkill" not in start_script


def test_production_images_do_not_install_or_configure_embedded_redis():
    dockerfile = (REPO / "gcp/cloud_run/Dockerfile").read_text(encoding="utf-8")

    assert "redis-server" not in dockerfile
    assert "CACHE_REDIS_HOST" not in dockerfile
    assert "CACHE_REDIS_PORT" not in dockerfile
    assert "CACHE_REDIS_DB" not in dockerfile


def test_production_gunicorn_workers_do_not_inherit_database_pools():
    start_script = (REPO / "gcp/cloud_run/start.sh").read_text(encoding="utf-8")
    commands = "\n".join(
        line for line in start_script.splitlines() if not line.lstrip().startswith("#")
    )
    assert "--preload" not in commands


def test_production_smoke_test_configuration_loads_without_sqlalchemy():
    script = """
import builtins
import runpy

original_import = builtins.__import__

def reject_sqlalchemy(name, *args, **kwargs):
    if name == "sqlalchemy" or name.startswith("sqlalchemy."):
        raise ModuleNotFoundError("production smoke tests do not install SQLAlchemy")
    return original_import(name, *args, **kwargs)

builtins.__import__ = reject_sqlalchemy
runpy.run_path("tests/integration/conftest.py", run_name="integration_conftest")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
