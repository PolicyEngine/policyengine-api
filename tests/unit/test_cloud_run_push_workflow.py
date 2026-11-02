"""The push workflow's Cloud Run jobs: services, order, tests and promotion."""

from __future__ import annotations

import re

from tests.unit.cloud_run_deploy_support import (
    PRODUCTION_CLOUD_RUN_SERVICE,
    REPO,
    STAGING_CLOUD_RUN_SERVICE,
    job_needs,
    job_step,
    push_workflow_jobs,
)
from tests.unit.cloud_run_deploy_support import (
    push_workflow as _push_workflow,
)
from tests.unit.cloud_run_deploy_support import (
    workflow_job_block as _workflow_job_block,
)

CLOUD_RUN_SERVICE_SCRIPTS = (
    "scripts/deploy_cloud_run_candidate.sh",
    "scripts/capture_cloud_run_service_state.sh",
    "scripts/resolve_cloud_run_candidate_state.sh",
    "scripts/set_cloud_run_revision.sh",
)
LIVE_TESTS_STEP = "Run live staging tests, one pytest worker per test"
RELEASE_TESTS_JOB = "release-tests"
RELEASE_COMMIT_CONDITION = (
    "(github.repository == 'PolicyEngine/policyengine-api')\n"
    "&& (github.event.head_commit.message == 'Update PolicyEngine API')\n"
)
RELEASE_TESTS_STEP = "Run release tests"
RELEASE_TESTS_COMMAND = "bash .github/scripts/run_release_tests.sh"
# The variables the release tests read when they ran inside the staging deploy
# job: that job's env, less the deployment settings run_release_tests.sh
# removes. The release-tests job keeps them, so the tests see the same inputs.
RELEASE_TESTS_JOB_ENV = {
    "SIM_ENTRYPOINT": "${{ vars.SIM_ENTRYPOINT }}",
    "SIMULATION_ENTRYPOINT_URL": "${{ secrets.SIMULATION_ENTRYPOINT_URL }}",
    "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": (
        "${{ vars.POLICYENGINE_DB_INSTANCE_CONNECTION_NAME }}"
    ),
    "PRODUCTION_CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET": (
        "${{ vars.PRODUCTION_CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET }}"
    ),
    "UV_PYTHON": "3.12",
}
RELEASE_TESTS_STEP_ENV = {
    "RUNTIME_CACHE_MODE": "local",
    "RUNTIME_CACHE_URL": "redis://127.0.0.1:6379/0",
    "RUNTIME_CACHE_ENVIRONMENT": "test",
    "RUNTIME_CACHE_SERVICE": "api",
    "POLICYENGINE_DB_PASSWORD": "${{ secrets.POLICYENGINE_DB_PASSWORD }}",
    "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN": (
        "${{ secrets.POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN }}"
    ),
    "OPENAI_API_KEY": "${{ secrets.OPENAI_API_KEY }}",
    "HUGGING_FACE_TOKEN": "${{ secrets.PE_UK_PRIVATE_HF_READ_TOKEN }}",
    "GATEWAY_AUTH_ISSUER": "${{ secrets.GATEWAY_AUTH_ISSUER }}",
    "GATEWAY_AUTH_AUDIENCE": "${{ secrets.GATEWAY_AUTH_AUDIENCE }}",
    "GATEWAY_AUTH_CLIENT_ID": "${{ secrets.GATEWAY_AUTH_CLIENT_ID }}",
    "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE": (
        "${{ secrets.GATEWAY_AUTH_CLIENT_SECRET_RESOURCE }}"
    ),
}


def test_staging_and_production_use_distinct_cloud_run_runtime_identities():
    workflow = _push_workflow()
    staging = _workflow_job_block(workflow, "deploy-cloud-run-staging")
    production = _workflow_job_block(workflow, "deploy-cloud-run-candidate")

    assert (
        "policyengine-api-cr-staging@policyengine-api.iam.gserviceaccount.com"
        in staging
    )
    assert "GCP_CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT" not in staging
    assert "GCP_CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT" in production


def test_push_workflow_pins_cloud_run_scaling_per_job():
    workflow = _push_workflow()
    staging_deploy = _workflow_job_block(workflow, "deploy-cloud-run-staging")
    production_deploy = _workflow_job_block(workflow, "deploy-cloud-run-candidate")

    assert 'CLOUD_RUN_MIN_INSTANCES: "0"' in staging_deploy
    assert 'CLOUD_RUN_MAX_INSTANCES: "1"' in staging_deploy
    assert 'CLOUD_RUN_MAX_INSTANCES: "8"' in production_deploy
    # Production keeps a service-level warm floor of 2; staging stays at 0.
    assert 'CLOUD_RUN_SERVICE_MIN_INSTANCES: "2"' in production_deploy
    assert 'CLOUD_RUN_SERVICE_MIN_INSTANCES: "0"' in staging_deploy
    # Revision-level min-instances must stay 0 EVERYWHERE in the workflow —
    # including workflow-level env, which flows into every job. Any mention
    # of the variable must be an explicit "0" pin.
    assert workflow.count("CLOUD_RUN_MIN_INSTANCES:") == workflow.count(
        'CLOUD_RUN_MIN_INSTANCES: "0"'
    )
    # The runtime-shape values live only in cloud_run_env.sh (where the
    # dry-run test validates them); no workflow-level or job-level override
    # may exist anywhere in this file.
    assert "CLOUD_RUN_CONCURRENCY" not in workflow
    assert "CLOUD_RUN_WEB_CONCURRENCY" not in workflow


def _workflow_job_names(workflow: str) -> list[str]:
    return re.findall(r"^  ([a-zA-Z0-9_-]+):$", workflow, flags=re.MULTILINE)


def test_push_workflow_isolates_staging_cloud_run_service():
    workflow = _push_workflow()
    staging_deploy = _workflow_job_block(workflow, "deploy-cloud-run-staging")
    staging_promote = _workflow_job_block(workflow, "promote-cloud-run-staging")
    production_deploy = _workflow_job_block(workflow, "deploy-cloud-run-candidate")

    staging_service_env = f"CLOUD_RUN_SERVICE: {STAGING_CLOUD_RUN_SERVICE}"
    assert staging_service_env in staging_deploy
    assert staging_service_env in staging_promote
    assert STAGING_CLOUD_RUN_SERVICE not in production_deploy
    assert f"CLOUD_RUN_SERVICE: {PRODUCTION_CLOUD_RUN_SERVICE}\n" in production_deploy


def test_every_cloud_run_job_pins_a_service():
    workflow = _push_workflow()

    for job_name in _workflow_job_names(workflow):
        block = _workflow_job_block(workflow, job_name)
        if not any(script in block for script in CLOUD_RUN_SERVICE_SCRIPTS):
            continue
        assert re.search(r"CLOUD_RUN_SERVICE: \S+", block), (
            f"Job {job_name} uses a service-targeting Cloud Run script without "
            "pinning CLOUD_RUN_SERVICE; the cloud_run_env.sh default silently "
            "targets production"
        )


def test_only_production_job_promotes_the_production_cloud_run_service():
    workflow = _push_workflow()

    for job_name in _workflow_job_names(workflow):
        block = _workflow_job_block(workflow, job_name)
        if "scripts/set_cloud_run_revision.sh" not in block:
            continue
        if job_name == "deploy-cloud-run-candidate":
            expected = f"CLOUD_RUN_SERVICE: {PRODUCTION_CLOUD_RUN_SERVICE}\n"
        else:
            expected = f"CLOUD_RUN_SERVICE: {STAGING_CLOUD_RUN_SERVICE}"
        assert expected in block, (
            f"Job {job_name} promotes Cloud Run traffic without pinning the "
            "expected service"
        )


def _assert_staging_deploy_tests_its_candidate(
    cloud_run_deploy: str, cloud_run_test_command: str
) -> None:
    # The release tests run in their own job, which this one needs.
    assert RELEASE_TESTS_COMMAND not in cloud_run_deploy
    assert "redis-server" not in cloud_run_deploy
    assert cloud_run_test_command in cloud_run_deploy
    assert "API_BASE_URL: ${{ steps.candidate.outputs.url }}" in cloud_run_deploy
    assert "environment: staging" in cloud_run_deploy
    assert "V2_MIGRATION_DATABASE_URL" in cloud_run_deploy
    assert cloud_run_deploy.index(
        "Wait for Cloud Run staging health"
    ) < cloud_run_deploy.index("Run staging integration tests")


def _assert_live_tests_run_in_parallel_after_readiness(
    workflow: str, parallel_live_tests: str, live_test_script: str
) -> None:
    assert "integration-tests-staging-cloud-run:" not in workflow
    assert "strategy:" not in parallel_live_tests
    assert "matrix:" not in parallel_live_tests
    assert "needs: deploy-cloud-run-staging" in parallel_live_tests
    assert "pip install" not in parallel_live_tests
    assert "run: make install" in parallel_live_tests
    live_readiness_command = (
        'bash .github/scripts/health_check.sh "'
        '${{ needs.deploy-cloud-run-staging.outputs.url }}/readiness-check"'
    )
    assert live_readiness_command in parallel_live_tests
    assert parallel_live_tests.index(
        "Install locked live test dependencies"
    ) < parallel_live_tests.index(live_readiness_command)
    assert parallel_live_tests.index(
        live_readiness_command
    ) < parallel_live_tests.index(LIVE_TESTS_STEP)
    assert "bash .github/scripts/run_live_staging_tests.sh" in parallel_live_tests
    assert "--dist load" in live_test_script
    assert "--maxschedchunk=1" in live_test_script
    assert "tests/integration/test_live_budget_window_cache.py" in live_test_script
    assert "tests/integration/test_live_calculate.py" in live_test_script
    assert "tests/integration/test_live_economy.py" in live_test_script
    assert "tests/integration/test_live_v2_policies.py" not in parallel_live_tests
    assert (
        "API_BASE_URL: ${{ needs.deploy-cloud-run-staging.outputs.url }}"
        in parallel_live_tests
    )
    assert "github.run_id" in parallel_live_tests
    assert "github.run_attempt" in parallel_live_tests


def _assert_promotion_verifies_the_tested_candidate(
    workflow: str, production_check: str, cloud_run_promotion: str
) -> None:
    assert "needs: promote-cloud-run-staging" in production_check
    assert "- integration-tests-staging-cloud-run" not in production_check
    assert "- integration-tests-staging-cloud-run" not in cloud_run_promotion
    assert "- parallel-live-simulation-tests-staging-cloud-run" in cloud_run_promotion
    assert "exercise-phase10-staging" not in workflow
    assert "run_phase10_staging_probe.sh" not in workflow
    assert "V2_FAILURE_DATABASE_URL_SECRET_RESOURCE" not in workflow
    assert "exercise-phase11-staging" not in workflow
    assert "run_phase11_staging_probe.sh" not in workflow
    assert "run_phase11_event_replay.sh" not in workflow
    assert "qualify-stage6-read-routes-staging" not in workflow
    assert "qualify_stage6_read_routes.sh" not in workflow
    assert "bash .github/scripts/set_cloud_run_revision.sh" in cloud_run_promotion
    assert (
        "CLOUD_RUN_TARGET_REVISION: "
        "${{ needs.deploy-cloud-run-staging.outputs.revision }}" in cloud_run_promotion
    )
    assert "Restore previous Cloud Run staging revision" in cloud_run_promotion
    assert (
        "${{ needs.deploy-cloud-run-staging.outputs.stable_url }}/readiness-check"
        in cloud_run_promotion
    )
    verify_index = cloud_run_promotion.index(
        "Verify exact tested Cloud Run staging candidate"
    )
    promote_index = cloud_run_promotion.index("Promote Cloud Run staging candidate")
    assert verify_index < promote_index
    assert (
        "CLOUD_RUN_EXPECTED_REVISION: "
        "${{ needs.deploy-cloud-run-staging.outputs.revision }}" in cloud_run_promotion
    )
    assert (
        "CLOUD_RUN_EXPECTED_IMAGE: "
        "${{ needs.deploy-cloud-run-staging.outputs.image }}" in cloud_run_promotion
    )


def test_push_workflow_tests_the_staging_candidate_before_promoting_it():
    workflow = _push_workflow()
    cloud_run_deploy = _workflow_job_block(workflow, "deploy-cloud-run-staging")
    parallel_live_tests = _workflow_job_block(
        workflow,
        "parallel-live-simulation-tests-staging-cloud-run",
    )
    cloud_run_promotion = _workflow_job_block(workflow, "promote-cloud-run-staging")
    production_check = _workflow_job_block(
        workflow,
        "ensure-production-model-version-aligns-with-sim-api",
    )
    cloud_run_test_command = (
        "python -m pytest tests/integration/test_cloud_run_candidate.py "
        "tests/integration/test_live_v2_metadata.py "
        "tests/integration/test_live_v2_policies.py -v"
    )
    live_test_script = (REPO / ".github/scripts/run_live_staging_tests.sh").read_text()

    _assert_staging_deploy_tests_its_candidate(cloud_run_deploy, cloud_run_test_command)
    _assert_live_tests_run_in_parallel_after_readiness(
        workflow, parallel_live_tests, live_test_script
    )
    _assert_promotion_verifies_the_tested_candidate(
        workflow, production_check, cloud_run_promotion
    )


def test_release_tests_run_in_their_own_job_before_the_staging_deploy():
    jobs = push_workflow_jobs()
    release_tests = jobs[RELEASE_TESTS_JOB]
    staging_deploy = jobs["deploy-cloud-run-staging"]

    # The staging deploy needs the release tests, so they pass before GCP
    # authentication, image publication and candidate deployment.
    assert RELEASE_TESTS_JOB in job_needs(staging_deploy)
    # They start with the run, beside the checks and the staging database jobs,
    # on the same release commits as the deploy.
    assert job_needs(release_tests) == []
    assert release_tests["if"] == RELEASE_COMMIT_CONDITION
    assert RELEASE_COMMIT_CONDITION.splitlines()[1] in staging_deploy["if"]
    # No GCP credentials: the tests ran before GCP authentication in the deploy
    # job too.
    assert release_tests["permissions"] == {"contents": "read"}
    for step in release_tests["steps"]:
        assert "google-github-actions" not in step.get("uses", "")


def test_release_tests_job_keeps_the_inputs_the_tests_read_in_the_deploy_job():
    release_tests = push_workflow_jobs()[RELEASE_TESTS_JOB]
    release_tests_step = job_step(release_tests, RELEASE_TESTS_STEP)

    assert release_tests["environment"] == "staging"
    assert release_tests["env"] == RELEASE_TESTS_JOB_ENV
    assert release_tests_step["run"] == RELEASE_TESTS_COMMAND
    # Each shard also gets its index, the shard count and where to report
    # (tests/unit/test_release_test_shards.py).
    assert {
        name: value
        for name, value in release_tests_step["env"].items()
        if not name.startswith("RELEASE_TEST_SHARD_")
    } == RELEASE_TESTS_STEP_ENV


def test_push_workflow_uses_local_redis_for_predeployment_test_suite():
    release_tests = push_workflow_jobs()[RELEASE_TESTS_JOB]
    step_names = [step.get("name") for step in release_tests["steps"]]
    test_step = job_step(release_tests, RELEASE_TESTS_STEP)

    assert job_step(release_tests, "Install release test dependencies")["run"] == (
        "sudo apt-get install -y redis-server"
    )
    assert job_step(release_tests, "Start release test Redis")["run"] == (
        "sudo systemctl start redis-server"
    )
    assert step_names.index("Start release test Redis") < step_names.index(
        RELEASE_TESTS_STEP
    )
    assert test_step["env"]["RUNTIME_CACHE_MODE"] == "local"
    assert test_step["env"]["RUNTIME_CACHE_URL"] == "redis://127.0.0.1:6379/0"
    assert test_step["env"]["RUNTIME_CACHE_ENVIRONMENT"] == "test"
    assert test_step["env"]["RUNTIME_CACHE_SERVICE"] == "api"
    release_tests = (REPO / ".github/scripts/run_release_tests.sh").read_text(
        encoding="utf-8"
    )
    for variable in (
        "ROUTE_IMPL_HEALTH",
        "ROUTE_IMPL_POLICY",
        "ROUTE_IMPL_HOUSEHOLD",
        "DB_READ_POLICY",
        "DB_WRITE_POLICY",
        "DB_READ_HOUSEHOLD",
        "DB_WRITE_HOUSEHOLD",
        "CLOUD_RUN_SERVICE",
        "V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE",
    ):
        assert f"-u {variable} " in release_tests


def test_push_workflow_staging_precedes_all_production_deployments():
    workflow = _push_workflow()
    docker_publish = _workflow_job_block(workflow, "docker")
    cloud_run_production = _workflow_job_block(workflow, "deploy-cloud-run-candidate")

    assert "- seed-v2-production-database" in cloud_run_production
    assert "- migrate-v1-production-cloud-sql" in cloud_run_production
    assert "needs: deploy-cloud-run-candidate" in docker_publish
    assert "compute_cloud_run_metadata.sh stage3-prod" in cloud_run_production
    assert "Build and push Cloud Run image" not in cloud_run_production


def test_push_workflow_serializes_deployments_without_cancelling_in_progress_run():
    workflow = _push_workflow()

    assert "concurrency:\n  group: deploy\n  cancel-in-progress: false" in workflow


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

    assert (
        "CLOUD_RUN_RUNTIME_SERVICE_ACCOUNT: "
        "policyengine-api-cr-staging@policyengine-api.iam.gserviceaccount.com"
        in cloud_run_staging
    )
    assert runtime_account_secret not in cloud_run_staging
    assert runtime_account_secret in cloud_run_production
    assert deploy_account_secret not in cloud_run_staging
    assert deploy_account_secret not in cloud_run_production


def test_push_workflow_promotes_production_cloud_run_after_candidate_smoke():
    workflow = _push_workflow()
    cloud_run_production = _workflow_job_block(workflow, "deploy-cloud-run-candidate")
    smoke_index = cloud_run_production.index(
        "python -m pytest tests/integration/test_cloud_run_candidate.py "
        "tests/integration/test_live_v2_metadata.py -v"
    )
    promote_index = cloud_run_production.index(
        "bash .github/scripts/set_cloud_run_revision.sh"
    )

    assert smoke_index < promote_index
    assert "SIM_ENTRYPOINT: ${{ vars.SIM_ENTRYPOINT }}" in cloud_run_production
    assert (
        "CLOUD_RUN_TARGET_REVISION: ${{ steps.candidate.outputs.revision }}"
        in cloud_run_production
    )
    assert (
        "CLOUD_RUN_EXPECTED_CURRENT_REVISION: "
        "${{ steps.previous.outputs.revision }}" in cloud_run_production
    )
    assert "Restore previous Cloud Run production revision" in cloud_run_production
    assert (
        "${{ steps.previous.outputs.stable_url }}/readiness-check"
        in cloud_run_production
    )
    verify_index = cloud_run_production.index(
        "Verify exact tested Cloud Run production candidate"
    )
    assert smoke_index < verify_index < promote_index
    assert (
        "CLOUD_RUN_EXPECTED_REVISION: ${{ steps.candidate.outputs.revision }}"
        in cloud_run_production
    )
    assert (
        "CLOUD_RUN_EXPECTED_IMAGE: ${{ steps.candidate.outputs.image }}"
        in cloud_run_production
    )


def test_push_workflow_never_uses_latest_or_tag_alias_for_cloud_run_traffic():
    workflow = _push_workflow()
    promotion_script = (REPO / ".github/scripts/set_cloud_run_revision.sh").read_text(
        encoding="utf-8"
    )

    assert "--to-tags" not in workflow
    assert "--to-latest" not in workflow.lower()
    assert "--to-revisions" in promotion_script
    assert '"${target_revision}=100"' in promotion_script


def test_push_workflow_wires_user_auth_settings_and_staging_test_user():
    workflow = _push_workflow()
    staging = _workflow_job_block(workflow, "deploy-cloud-run-staging")
    production = _workflow_job_block(workflow, "deploy-cloud-run-candidate")

    for job in (staging, production):
        for line in (
            "PUBLIC_API_AUTH_REQUIRED: ${{ vars.PUBLIC_API_AUTH_REQUIRED }}",
            "PUBLIC_API_AUTH_ISSUER: ${{ vars.PUBLIC_API_AUTH_ISSUER }}",
            "PUBLIC_API_AUTH_AUDIENCE: ${{ vars.PUBLIC_API_AUTH_AUDIENCE }}",
        ):
            assert line in job
    # Management API deletion is production-only: the staging live test
    # deletes its own account, which would delete the CI user from Auth0.
    for line in (
        "AUTH0_MANAGEMENT_DOMAIN: ${{ vars.AUTH0_MANAGEMENT_DOMAIN }}",
        "AUTH0_MANAGEMENT_CLIENT_ID: ${{ vars.AUTH0_MANAGEMENT_CLIENT_ID }}",
        "AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE: "
        "${{ secrets.AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE }}",
    ):
        assert line in production
    assert "AUTH0_MANAGEMENT" not in staging

    # The release tests never see the signed-in user settings.
    release_tests_job = _workflow_job_block(workflow, RELEASE_TESTS_JOB)
    assert "PUBLIC_API_AUTH" not in release_tests_job
    assert f"run: {RELEASE_TESTS_COMMAND}" in release_tests_job
    release_tests = (REPO / ".github/scripts/run_release_tests.sh").read_text(
        encoding="utf-8"
    )
    for name in (
        "PUBLIC_API_AUTH_REQUIRED",
        "PUBLIC_API_AUTH_ISSUER",
        "PUBLIC_API_AUTH_AUDIENCE",
    ):
        assert f"-u {name} " in release_tests

    integration_start = staging.index("- name: Run staging integration tests")
    integration = staging[integration_start:]
    assert "tests/integration/test_live_v2_policies.py" in integration
    for name in (
        "STAGING_AUTH0_TEST_DOMAIN: ${{ vars.STAGING_AUTH0_TEST_DOMAIN }}",
        "STAGING_AUTH0_TEST_AUDIENCE: ${{ vars.STAGING_AUTH0_TEST_AUDIENCE }}",
        "STAGING_AUTH0_TEST_CLIENT_ID: ${{ secrets.STAGING_AUTH0_TEST_CLIENT_ID }}",
        "STAGING_AUTH0_TEST_CLIENT_SECRET: "
        "${{ secrets.STAGING_AUTH0_TEST_CLIENT_SECRET }}",
        "STAGING_AUTH0_TEST_USERNAME: ${{ secrets.STAGING_AUTH0_TEST_USERNAME }}",
        "STAGING_AUTH0_TEST_PASSWORD: ${{ secrets.STAGING_AUTH0_TEST_PASSWORD }}",
        "STAGING_AUTH0_TEST_REALM: ${{ vars.STAGING_AUTH0_TEST_REALM }}",
    ):
        assert name in integration
    assert "STAGING_AUTH0_TEST" not in production
