from __future__ import annotations

import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
PUSH_WORKFLOW = REPO / ".github/workflows/push.yml"
REMOVED_JOB_NAMES = (
    "deploy-staging",
    "integration-tests-staging",
    "stop-staging-app-engine-version",
    "deploy-production-candidate",
    "promote-production",
    "cleanup-prod-app-engine-versions",
)
REMOVED_DEPLOYMENT_PATHS = (
    ".gcloudignore",
    ".dockerignore",
    "gcp/Dockerfile",
    "gcp/dispatch.yaml",
    "gcp/export.py",
    "gcp/policyengine_api/Dockerfile",
    "gcp/policyengine_api/app.yaml",
    "gcp/policyengine_api/start.sh",
    "policyengine_api/app_engine_runtime.py",
    ".github/scripts/build_app_engine_image.sh",
    ".github/scripts/cleanup_app_engine_versions.sh",
    ".github/scripts/deploy_app_engine_version.sh",
    ".github/scripts/get_app_engine_version_url.sh",
    ".github/scripts/prepare_app_engine_bundle.sh",
    ".github/scripts/promote_app_engine_version.sh",
    ".github/scripts/stop_app_engine_version.sh",
    ".github/scripts/validate_app_engine_deploy_env.sh",
)


def _job_block(workflow: str, job_name: str) -> str:
    match = re.search(
        rf"^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:|\Z)",
        workflow,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"Missing workflow job {job_name}"
    return match.group("body")


def test_app_engine_deployment_assets_are_absent() -> None:
    workflow = PUSH_WORKFLOW.read_text(encoding="utf-8")

    for job_name in REMOVED_JOB_NAMES:
        assert f"  {job_name}:" not in workflow
    for relative_path in REMOVED_DEPLOYMENT_PATHS:
        assert not (REPO / relative_path).exists()

    active_deployment_text = workflow + (REPO / "Makefile").read_text(encoding="utf-8")
    for script in (REPO / ".github/scripts").glob("*.sh"):
        active_deployment_text += script.read_text(encoding="utf-8")

    assert "gcloud app deploy" not in active_deployment_text


def test_cloud_run_is_the_complete_release_sequence() -> None:
    workflow = PUSH_WORKFLOW.read_text(encoding="utf-8")
    staging_seed = _job_block(workflow, "seed-v2-staging-database")
    staging_deploy = _job_block(workflow, "deploy-cloud-run-staging")
    staging_integration = _job_block(
        workflow,
        "integration-tests-staging-cloud-run",
    )
    staging_promotion = _job_block(workflow, "promote-cloud-run-staging")
    staging_phase10_exercise = _job_block(workflow, "exercise-phase10-staging")
    production_check = _job_block(
        workflow,
        "ensure-production-model-version-aligns-with-sim-api",
    )
    production_seed = _job_block(workflow, "seed-v2-production-database")
    production_deploy = _job_block(workflow, "deploy-cloud-run-candidate")
    docker_publish = _job_block(workflow, "docker")

    assert "  release-tests:" not in workflow
    assert "migrate-v1-staging-cloud-sql" in staging_seed
    assert "- seed-v2-staging-database" in staging_deploy
    assert "make test" in staging_deploy
    assert staging_deploy.index("make test") < staging_deploy.index(
        'uses: "google-github-actions/auth@v2"'
    )
    assert staging_deploy.index("make test") < staging_deploy.index(
        "Build and push Cloud Run image"
    )
    assert "needs: deploy-cloud-run-staging" in staging_integration
    assert "- integration-tests-staging-cloud-run" in staging_promotion
    assert "- promote-cloud-run-staging" in staging_phase10_exercise
    assert "needs: exercise-phase10-staging" in production_check
    assert "migrate-v1-production-cloud-sql" in production_seed
    assert "needs: seed-v2-production-database" in production_deploy
    assert "needs: deploy-cloud-run-candidate" in docker_publish


def test_repository_contains_no_cloud_decommission_automation() -> None:
    operational_text = PUSH_WORKFLOW.read_text(encoding="utf-8")
    operational_text += (REPO / "Makefile").read_text(encoding="utf-8")
    for script in (REPO / ".github/scripts").glob("*.sh"):
        assert "decommission" not in script.name
        operational_text += script.read_text(encoding="utf-8")

    prohibited_operations = (
        "gcloud app domain-mappings delete",
        "gcloud compute backend-services delete bs-app-engine",
        "gcloud compute network-endpoint-groups delete neg-app-engine",
        "gcloud artifacts repositories delete gae-flexible",
    )
    for operation in prohibited_operations:
        assert operation not in operational_text
