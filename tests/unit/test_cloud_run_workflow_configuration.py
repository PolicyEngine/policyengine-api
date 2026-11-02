"""Workflow configuration: simulation routing, database targets and secrets."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tests.unit.cloud_run_deploy_support import (
    REPO,
    TEST_V2_ENVIRONMENT,
    TEST_V2_PROJECT_REF,
)
from tests.unit.cloud_run_deploy_support import (
    pr_workflow as _pr_workflow,
)
from tests.unit.cloud_run_deploy_support import (
    push_workflow as _push_workflow,
)
from tests.unit.cloud_run_deploy_support import (
    run_bash as _run_bash,
)
from tests.unit.cloud_run_deploy_support import (
    workflow_job_block as _workflow_job_block,
)

if TYPE_CHECKING:
    from pathlib import Path


def _multiline_run_block_lengths(workflow_path: Path) -> list[tuple[int, int]]:
    lines = workflow_path.read_text(encoding="utf-8").splitlines()
    blocks: list[tuple[int, int]] = []

    for line_index, line in enumerate(lines):
        match = re.match(r"^(\s*)run: \|", line)
        if match is None:
            continue

        indent = len(match.group(1))
        body_lines = 0
        for body_line in lines[line_index + 1 :]:
            if body_line.strip() and len(body_line) - len(body_line.lstrip()) <= indent:
                break
            if body_line.strip():
                body_lines += 1
        blocks.append((line_index + 1, body_lines))

    return blocks


def test_deployment_jobs_read_supabase_identity_from_github_environment_variables():
    workflow = _push_workflow()

    for job_name in (
        "deploy-cloud-run-staging",
        "deploy-cloud-run-candidate",
    ):
        job = _workflow_job_block(workflow, job_name)
        assert "V2_SUPABASE_PROJECT_REF: ${{ vars.V2_SUPABASE_PROJECT_REF }}" in job
        assert "V2_SUPABASE_ENVIRONMENT: ${{ vars.V2_SUPABASE_ENVIRONMENT }}" in job

    for job_name in ("deploy-cloud-run-staging", "deploy-cloud-run-candidate"):
        job = _workflow_job_block(workflow, job_name)
        assert (
            "V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE: "
            "${{ secrets.V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE }}" in job
        )

    assert TEST_V2_PROJECT_REF not in workflow
    assert TEST_V2_ENVIRONMENT not in workflow


def test_household_event_workflow_uses_one_explicit_authorized_identity():
    workflow = (
        REPO / ".github/workflows/process-v1-household-mirror-event.yml"
    ).read_text(encoding="utf-8")
    operator_script = (
        REPO / ".github/scripts/run_household_mirror_event_operator.sh"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "type: choice" in workflow
    assert "environment: ${{ inputs.deployment_environment }}" in workflow
    assert "service_account: ${{ vars.GCP_DB_MIGRATION_SERVICE_ACCOUNT }}" in workflow
    assert "HOUSEHOLD_MIRROR_OPERATOR_IDENTITY" in workflow
    assert "ALLOWED_HOUSEHOLD_MIRROR_OPERATOR_IDENTITY" in workflow
    assert "V2_DATA_WRITE_DATABASE_URL" in workflow
    assert "--legacy-household-id" in workflow
    assert "POLICYENGINE_DB_MIGRATION_PASSWORD_SECRET" in operator_script
    assert 'POLICYENGINE_DB_PROXY_PORT="3307"' in operator_script
    assert "validate_database_environment.sh cloud-sql" in operator_script
    assert "validate_database_environment.sh supabase" in operator_script
    assert "process_v1_household_mirror_event.py" in operator_script
    assert "start_cloud_sql_proxy.sh" in workflow
    assert "stop_cloud_sql_proxy.sh" in workflow


def test_manual_simulation_entrypoint_ramp_is_removed():
    assert not (REPO / ".github/scripts/ramp_simulation_entrypoint.sh").exists()
    assert not (REPO / ".github/workflows/ramp-simulation-entrypoint.yml").exists()


def test_workflows_do_not_store_simulation_selector_in_git():
    workflow = _push_workflow()
    pr_workflow = _pr_workflow()

    assert not (REPO / ".github/simulation-entrypoint-mode").exists()
    for workflow_text in (workflow, pr_workflow):
        assert (
            workflow_text.count(
                "OLD_SIMULATION_GATEWAY_URL: ${{ vars.OLD_SIMULATION_GATEWAY_URL }}"
            )
            == 1
        )
        assert (
            "SIM_ENTRYPOINT: ${{ vars.SIM_ENTRYPOINT }}"
            not in workflow_text.split("jobs:", maxsplit=1)[0]
        )


def test_workflows_scope_simulation_routing_config_to_github_environments():
    selector_env = "SIM_ENTRYPOINT: ${{ vars.SIM_ENTRYPOINT }}"
    secret_env = "SIMULATION_ENTRYPOINT_URL: ${{ secrets.SIMULATION_ENTRYPOINT_URL }}"
    pr_workflow = _pr_workflow()
    push_workflow = _push_workflow()

    assert secret_env not in pr_workflow.split("jobs:", maxsplit=1)[0]
    assert secret_env not in push_workflow.split("jobs:", maxsplit=1)[0]
    assert selector_env not in pr_workflow.split("jobs:", maxsplit=1)[0]
    assert selector_env not in push_workflow.split("jobs:", maxsplit=1)[0]

    environment_jobs = (
        (
            pr_workflow,
            "ensure-policyengine-bundle-supported-by-simulation-api",
            "staging",
        ),
        (
            push_workflow,
            "ensure-staging-model-version-aligns-with-sim-api",
            "staging",
        ),
        (push_workflow, "release-tests", "staging"),
        (push_workflow, "deploy-cloud-run-staging", "staging"),
        (
            push_workflow,
            "ensure-production-model-version-aligns-with-sim-api",
            "production",
        ),
        (push_workflow, "deploy-cloud-run-candidate", "production"),
    )
    for workflow_text, job_name, environment in environment_jobs:
        job = _workflow_job_block(workflow_text, job_name)
        assert f"environment: {environment}" in job
        assert selector_env in job
        assert secret_env in job


def test_pr_build_and_test_jobs_require_simulation_bundle_compatibility():
    workflow = _pr_workflow()
    compatibility_job = "ensure-policyengine-bundle-supported-by-simulation-api"

    for job_name in (
        "test_container_builds",
        "test_cloud_run_container_builds",
        "test_env_vars",
        "test",
    ):
        job = _workflow_job_block(workflow, job_name)
        assert compatibility_job in job


def test_cloud_run_candidate_jobs_use_environment_scoped_migration_selectors():
    workflow = _push_workflow()
    selectors = (
        "ROUTE_IMPL_HEALTH",
        "ROUTE_IMPL_SPECIFICATION",
        "ROUTE_IMPL_METADATA",
        "ROUTE_IMPL_POLICY",
        "ROUTE_IMPL_HOUSEHOLD",
        "DB_READ_POLICY",
        "DB_WRITE_POLICY",
        "DB_READ_HOUSEHOLD",
        "DB_WRITE_HOUSEHOLD",
    )

    for job_name, environment in (
        ("deploy-cloud-run-staging", "staging"),
        ("promote-cloud-run-staging", "staging"),
        ("deploy-cloud-run-candidate", "production"),
    ):
        job = _workflow_job_block(workflow, job_name)
        assert f"environment: {environment}" in job
        for selector in selectors:
            assert f"{selector}: ${{{{ vars.{selector} }}}}" in job


def test_all_deploy_jobs_use_github_database_instance_variable():
    workflow = _push_workflow()
    instance_env = (
        "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME: "
        "${{ vars.POLICYENGINE_DB_INSTANCE_CONNECTION_NAME }}"
    )

    for job_name in (
        "deploy-cloud-run-staging",
        "deploy-cloud-run-candidate",
    ):
        assert instance_env in _workflow_job_block(workflow, job_name)


def test_deployment_consumers_require_selector_from_environment():
    consumers = (
        ".github/request-simulation-model-versions.sh",
        ".github/scripts/validate_cloud_run_deploy_env.sh",
    )

    for consumer in consumers:
        script = (REPO / consumer).read_text(encoding="utf-8")
        assert "source .github/scripts/simulation_entrypoint_env.sh" in script
        assert "simulation_entrypoint_load_git_selection" not in script


def test_workflows_never_depend_on_opaque_legacy_simulation_url_secret():
    workflows = "\n".join(
        workflow.read_text(encoding="utf-8")
        for workflow in (REPO / ".github/workflows").glob("*.y*ml")
    )

    assert "SIMULATION_API_URL" not in workflows
    assert "vars.SIMULATION_ENTRYPOINT_URL" not in workflows
    assert "secrets.SIMULATION_ENTRYPOINT_URL" in workflows
    assert "secrets.OLD_SIMULATION_GATEWAY_URL" not in workflows


def test_push_workflow_does_not_pass_raw_secrets_to_cloud_run_deploy_commands():
    workflow = _push_workflow()
    cloud_run_staging = _workflow_job_block(workflow, "deploy-cloud-run-staging")
    cloud_run_production = _workflow_job_block(workflow, "deploy-cloud-run-candidate")
    staging_deploy_start = cloud_run_staging.index(
        "- name: Deploy tagged Cloud Run staging candidate"
    )
    staging_deploy_end = cloud_run_staging.index(
        "- name: Resolve exact Cloud Run staging candidate",
        staging_deploy_start,
    )
    staging_deploy = cloud_run_staging[staging_deploy_start:staging_deploy_end]
    production_deploy_start = cloud_run_production.index(
        "- name: Deploy tagged Cloud Run candidate"
    )
    production_deploy_end = cloud_run_production.index(
        "- name: Resolve exact Cloud Run production candidate",
        production_deploy_start,
    )
    production_deploy = cloud_run_production[
        production_deploy_start:production_deploy_end
    ]
    raw_secret_envs = (
        "POLICYENGINE_DB_PASSWORD: ${{ secrets.POLICYENGINE_DB_PASSWORD }}",
        (
            "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN: "
            "${{ secrets.POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN }}"
        ),
        "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}",
        "HUGGING_FACE_TOKEN: ${{ secrets.PE_UK_PRIVATE_HF_READ_TOKEN }}",
    )

    for raw_secret_env in raw_secret_envs:
        assert raw_secret_env not in staging_deploy
        assert raw_secret_env not in production_deploy


def test_push_workflow_syncs_environment_specific_secrets_before_deployment():
    workflow = _push_workflow()
    cloud_run_staging = _workflow_job_block(workflow, "deploy-cloud-run-staging")
    cloud_run_production = _workflow_job_block(workflow, "deploy-cloud-run-candidate")
    release_test_step = _workflow_job_block(workflow, "release-tests")
    release_test_step = release_test_step[
        release_test_step.index("- name: Run release tests") :
    ]
    staging_sync_start = cloud_run_staging.index(
        "- name: Synchronize shared Cloud Run runtime secrets"
    )
    staging_sync_end = cloud_run_staging.index(
        "- name: Capture current Cloud Run staging state",
        staging_sync_start,
    )
    staging_sync_step = cloud_run_staging[staging_sync_start:staging_sync_end]
    production_sync_start = cloud_run_production.index(
        "- name: Synchronize complete Cloud Run runtime secret batch"
    )
    production_sync_end = cloud_run_production.index(
        "- name: Capture current Cloud Run production state",
        production_sync_start,
    )
    production_sync_step = cloud_run_production[
        production_sync_start:production_sync_end
    ]

    release_test_secret_envs = (
        "POLICYENGINE_DB_PASSWORD: ${{ secrets.POLICYENGINE_DB_PASSWORD }}",
        (
            "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN: "
            "${{ secrets.POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN }}"
        ),
        "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}",
        "HUGGING_FACE_TOKEN: ${{ secrets.PE_UK_PRIVATE_HF_READ_TOKEN }}",
    )
    shared_sync_secret_envs = (
        (
            "POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN: "
            "${{ secrets.POLICYENGINE_GITHUB_MICRODATA_AUTH_TOKEN }}"
        ),
        "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}",
        ("PE_UK_PRIVATE_HF_READ_TOKEN: ${{ secrets.PE_UK_PRIVATE_HF_READ_TOKEN }}"),
    )
    for raw_secret_env in release_test_secret_envs:
        assert release_test_step.count(raw_secret_env) == 1
    for raw_secret_env in shared_sync_secret_envs:
        assert staging_sync_step.count(raw_secret_env) == 1
        assert production_sync_step.count(raw_secret_env) == 1
    database_secret_env = (
        "POLICYENGINE_DB_PASSWORD: ${{ secrets.POLICYENGINE_DB_PASSWORD }}"
    )
    assert database_secret_env not in staging_sync_step
    assert production_sync_step.count(database_secret_env) == 1
    assert "run: bash .github/scripts/sync_cloud_run_secrets.sh\n" in staging_sync_step
    assert "--include-database-password" not in staging_sync_step
    assert (
        "run: bash .github/scripts/sync_cloud_run_secrets.sh "
        "--include-database-password" in production_sync_step
    )


def test_changelog_fragment_script_is_shell_syntax_valid():
    result = _run_bash("-n", ".github/scripts/check_changelog_fragment.sh")

    assert result.returncode == 0, result.stderr


def test_workflows_do_not_inline_long_run_blocks():
    oversized_blocks = []
    for workflow_path in (REPO / ".github/workflows").glob("*.y*ml"):
        for line_number, body_lines in _multiline_run_block_lengths(workflow_path):
            if body_lines > 4:
                oversized_blocks.append(
                    f"{workflow_path.relative_to(REPO)}:{line_number} has "
                    f"{body_lines} inline run lines"
                )

    assert oversized_blocks == []
