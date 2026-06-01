from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def _script_env(**overrides: str) -> dict[str, str]:
    env = {
        "HOME": os.environ.get("HOME", ""),
        "PATH": os.environ["PATH"],
        "CLOUD_RUN_DRY_RUN": "1",
    }
    env.update(overrides)
    return env


def _required_runtime_env() -> dict[str, str]:
    return {
        "POLICYENGINE_DB_PASSWORD": "db-password",
        "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN": "github-token",
        "ANTHROPIC_API_KEY": "anthropic-key",
        "OPENAI_API_KEY": "openai-key",
        "HUGGING_FACE_TOKEN": "hf-token",
        "SIMULATION_API_URL": "https://simulation.example.test",
        "GATEWAY_AUTH_ISSUER": "https://issuer.example.test",
        "GATEWAY_AUTH_AUDIENCE": "simulation-gateway",
        "GATEWAY_AUTH_CLIENT_ID": "client-id",
        "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE": (
            "projects/policyengine-api/secrets/gateway-client-secret/versions/latest"
        ),
    }


def _run_script(path: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", path],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cloud_run_startup_uses_asgi_entrypoint():
    start_script = (REPO / "gcp/cloud_run/start.sh").read_text(encoding="utf-8")

    assert "policyengine_api.asgi:app" in start_script
    assert "policyengine_api.api" not in start_script


def test_validate_cloud_run_deploy_env_reports_missing_runtime_config():
    result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        _script_env(),
    )

    assert result.returncode == 1
    assert "Missing required Cloud Run deployment configuration" in result.stderr
    assert "POLICYENGINE_DB_PASSWORD" in result.stderr
    assert "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE" in result.stderr


def test_build_cloud_run_image_dry_run_uses_cloud_run_dockerfile():
    dockerignore = REPO / "gcp/cloud_run/Dockerfile.dockerignore"

    assert dockerignore.exists()
    assert "policyengine_api/data/*.db" in dockerignore.read_text(encoding="utf-8")

    result = _run_script(
        ".github/scripts/build_cloud_run_image.sh",
        _script_env(
            GITHUB_SHA="1234567890abcdef",
            GITHUB_RUN_NUMBER="42",
        ),
    )

    assert result.returncode == 0, result.stderr
    assert "gcp/cloud_run/Dockerfile" in result.stdout
    assert "docker push" in result.stdout
    assert (
        "us-central1-docker.pkg.dev/policyengine-api/policyengine-api/"
        "policyengine-api:1234567890abcdef"
    ) in result.stdout


def test_deploy_cloud_run_candidate_dry_run_never_shifts_traffic():
    result = _run_script(
        ".github/scripts/deploy_cloud_run_candidate.sh",
        _script_env(
            **_required_runtime_env(),
            CLOUD_RUN_IMAGE_URI="us-central1-docker.pkg.dev/project/repo/api:sha",
            CLOUD_RUN_TAG="stage3-test",
        ),
    )

    assert result.returncode == 0, result.stderr
    assert "gcloud run deploy" in result.stdout
    assert "--no-traffic" in result.stdout
    assert "stage3-test" in result.stdout
    assert "--to-latest" not in result.stdout
    assert "update-traffic" not in result.stdout


def test_get_cloud_run_tag_url_dry_run_uses_candidate_tag():
    result = _run_script(
        ".github/scripts/get_cloud_run_tag_url.sh",
        _script_env(CLOUD_RUN_TAG="stage3-test", CLOUD_RUN_SERVICE="policyengine-api"),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        "https://stage3-test---policyengine-api-dry-run.a.run.app"
    )
