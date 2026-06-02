from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
PRODUCTION_CLOUD_SQL_INSTANCE = "policyengine-api:us-central1:policyengine-api-data"
DEDICATED_CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT = (
    "policyengine-api-cr-runtime@policyengine-api.iam.gserviceaccount.com"
)


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


def _push_workflow() -> str:
    return (REPO / ".github/workflows/push.yml").read_text(encoding="utf-8")


def _workflow_job_block(workflow: str, job_name: str) -> str:
    match = re.search(
        rf"^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:|\Z)",
        workflow,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"Missing workflow job {job_name}"
    return match.group("body")


def test_cloud_run_startup_uses_asgi_entrypoint():
    start_script = (REPO / "gcp/cloud_run/start.sh").read_text(encoding="utf-8")

    assert "policyengine_api.asgi:app" in start_script
    assert "policyengine_api.api" not in start_script


def test_cloud_run_startup_script_is_shell_syntax_valid():
    result = subprocess.run(
        ["bash", "-n", "gcp/cloud_run/start.sh"],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_cloud_run_dockerfile_runs_startup_with_bash():
    dockerfile = (REPO / "gcp/cloud_run/Dockerfile").read_text(encoding="utf-8")

    assert 'CMD ["/bin/bash", "/app/start.sh"]' in dockerfile
    assert 'CMD ["/bin/sh", "/app/start.sh"]' not in dockerfile


def test_cloud_run_startup_supervises_redis_and_uvicorn_children():
    start_script = (REPO / "gcp/cloud_run/start.sh").read_text(encoding="utf-8")

    assert "#!/usr/bin/env bash" in start_script
    assert 'redis_pid="$!"' in start_script
    assert 'uvicorn_pid="$!"' in start_script
    assert "REDIS_READY_MAX_ATTEMPTS" in start_script
    assert "Redis exited before becoming ready" in start_script
    assert "Redis did not become ready" in start_script
    assert "Redis exited; stopping Cloud Run container" in start_script
    assert "Uvicorn exited; stopping Cloud Run container" in start_script
    assert 'wait -n "$redis_pid" "$uvicorn_pid"' in start_script
    assert 'kill -0 "$redis_pid"' in start_script
    assert 'kill -0 "$uvicorn_pid"' in start_script
    assert "trap 'shutdown; exit 143' INT TERM" in start_script
    assert "pkill" not in start_script
    assert re.search(r"(?m)^ *wait 2>/dev/null", start_script) is None


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
    assert (
        f"--service-account {DEDICATED_CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT}"
        in result.stdout
    )
    assert f"--add-cloudsql-instances {PRODUCTION_CLOUD_SQL_INSTANCE}" in result.stdout
    assert (
        f"POLICYENGINE_DB_INSTANCE_CONNECTION_NAME={PRODUCTION_CLOUD_SQL_INSTANCE}"
        in result.stdout
    )
    assert "CLOUD_RUN_INTERNAL_PROBES" not in result.stdout
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


def test_get_cloud_run_service_url_dry_run_uses_service_url():
    result = _run_script(
        ".github/scripts/get_cloud_run_service_url.sh",
        _script_env(CLOUD_RUN_SERVICE="policyengine-api"),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "https://policyengine-api-dry-run.a.run.app"


def test_promote_cloud_run_tag_dry_run_shifts_service_traffic_to_tag():
    result = _run_script(
        ".github/scripts/promote_cloud_run_tag.sh",
        _script_env(CLOUD_RUN_TAG="stage3-test", CLOUD_RUN_SERVICE="policyengine-api"),
    )

    assert result.returncode == 0, result.stderr
    assert "gcloud run services update-traffic policyengine-api" in result.stdout
    assert "--to-tags stage3-test=100" in result.stdout
    assert "--to-latest" not in result.stdout


def test_push_workflow_tests_app_engine_and_cloud_run_staging_tracks():
    workflow = _push_workflow()
    app_engine_tests = _workflow_job_block(workflow, "integration-tests-staging")
    cloud_run_tests = _workflow_job_block(
        workflow,
        "integration-tests-staging-cloud-run",
    )
    cloud_run_promotion = _workflow_job_block(workflow, "promote-cloud-run-staging")
    production_gate = _workflow_job_block(
        workflow,
        "ensure-production-model-version-aligns-with-sim-api",
    )
    live_test_command = (
        "python -m pytest tests/integration/test_live_calculate.py "
        "tests/integration/test_live_economy.py "
        "tests/integration/test_live_budget_window_cache.py -v"
    )

    assert live_test_command in app_engine_tests
    assert live_test_command in cloud_run_tests
    assert "API_BASE_URL: ${{ needs.deploy-staging.outputs.url }}" in app_engine_tests
    assert (
        "API_BASE_URL: ${{ needs.deploy-cloud-run-staging.outputs.url }}"
        in cloud_run_tests
    )
    assert "- integration-tests-staging" in production_gate
    assert "- promote-cloud-run-staging" in production_gate
    assert "- integration-tests-staging-cloud-run" not in production_gate
    assert "- integration-tests-staging" in cloud_run_promotion
    assert "- integration-tests-staging-cloud-run" in cloud_run_promotion
    assert "bash .github/scripts/promote_cloud_run_tag.sh" in cloud_run_promotion
    assert "bash .github/scripts/get_cloud_run_service_url.sh" in cloud_run_promotion


def test_push_workflow_deploys_production_tracks_in_parallel():
    workflow = _push_workflow()
    app_engine_production = _workflow_job_block(workflow, "deploy-production")
    cloud_run_production = _workflow_job_block(workflow, "deploy-cloud-run-candidate")

    assert (
        "needs: ensure-production-model-version-aligns-with-sim-api"
        in app_engine_production
    )
    assert (
        "needs: ensure-production-model-version-aligns-with-sim-api"
        in cloud_run_production
    )
    assert "needs: deploy-production" not in cloud_run_production
    assert "stage3-prod-" in cloud_run_production
    assert "Build and push Cloud Run image" not in cloud_run_production


def test_push_workflow_uses_dedicated_cloud_run_runtime_service_account():
    workflow = _push_workflow()
    cloud_run_staging = _workflow_job_block(workflow, "deploy-cloud-run-staging")
    cloud_run_production = _workflow_job_block(workflow, "deploy-cloud-run-candidate")

    runtime_account_secret = (
        "CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT: "
        "${{ secrets.GCP_CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT }}"
    )
    deploy_account_secret = (
        "CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT: ${{ secrets.GCP_DEPLOY_SERVICE_ACCOUNT }}"
    )

    assert runtime_account_secret in cloud_run_staging
    assert runtime_account_secret in cloud_run_production
    assert deploy_account_secret not in cloud_run_staging
    assert deploy_account_secret not in cloud_run_production


def test_push_workflow_promotes_production_cloud_run_after_candidate_smoke():
    workflow = _push_workflow()
    cloud_run_production = _workflow_job_block(workflow, "deploy-cloud-run-candidate")
    smoke_index = cloud_run_production.index(
        "python -m pytest tests/integration/test_cloud_run_candidate.py -v"
    )
    promote_index = cloud_run_production.index(
        "bash .github/scripts/promote_cloud_run_tag.sh"
    )

    assert smoke_index < promote_index
    assert "bash .github/scripts/get_cloud_run_service_url.sh" in cloud_run_production
