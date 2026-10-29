"""Deployment ordering and credential-isolation tests for Stage 9."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.unit.cloud_run_deploy_support import job_needs, push_workflow_jobs

REPO = Path(__file__).resolve().parents[3]

# Per environment: the v1 Cloud SQL schema upgrade, the v2 seeding, the job
# that deploys the Cloud Run candidate, and the job both database jobs start
# after.
DATABASE_JOBS_BY_ENVIRONMENT = {
    "staging": {
        "v1_upgrade": "migrate-v1-staging-cloud-sql",
        "v2_seeding": "seed-v2-staging-database",
        "candidate_deploy": "deploy-cloud-run-staging",
        "start_after": "publish-git-tag",
    },
    "production": {
        "v1_upgrade": "migrate-v1-production-cloud-sql",
        "v2_seeding": "seed-v2-production-database",
        "candidate_deploy": "deploy-cloud-run-candidate",
        "start_after": "ensure-production-model-version-aligns-with-sim-api",
    },
}


def _read(relative_path: str) -> str:
    return (REPO / relative_path).read_text(encoding="utf-8")


def _job(workflow: str, name: str) -> str:
    match = re.search(
        rf"^  {re.escape(name)}:\n(?P<body>.*?)(?=^  [\w-]+:|\Z)",
        workflow,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None
    return match.group("body")


def _step(workflow: str, name: str, next_name: str | None = None) -> str:
    start = workflow.index(f"      - name: {name}")
    end = len(workflow)
    if next_name is not None:
        end = workflow.index(f"      - name: {next_name}", start)
    return workflow[start:end]


def test_reusable_seeding_workflow_separates_database_credentials() -> None:
    workflow = _read(".github/workflows/seed-v2-database.yml")
    migration = _step(
        workflow,
        "Upgrade and verify the v2 schema",
        "Seed and validate the v2 metadata catalog",
    )
    publication = _step(
        workflow,
        "Seed and validate the v2 metadata catalog",
    )

    assert not (REPO / ".github/workflows/initialize-v2-metadata.yml").exists()
    assert workflow.startswith("name: Seed v2 database\n")
    assert "workflow_call:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "environment: ${{ inputs.deployment_environment }}" in workflow
    assert "V2_MIGRATION_DATABASE_URL" in migration
    assert "V2_DATA_WRITE_DATABASE_URL" not in migration
    assert "V2_DATA_WRITE_DATABASE_URL" in publication
    assert "V2_MIGRATION_DATABASE_URL" not in publication
    assert "V2_RUNTIME_DATABASE_URL" not in workflow
    assert "scripts/publish_v2_metadata_catalog.py" in publication
    assert (REPO / "scripts/publish_v2_metadata_catalog.py").is_file()
    assert not (REPO / "scripts/initialize_v2_metadata.py").exists()


def test_schema_upgrade_precedes_atomic_catalog_publication() -> None:
    script = _read(".github/scripts/migrate_v2_metadata_schema.sh")
    upgrade = script.index("upgrade head")
    current = script.index("current --check-heads")
    drift = script.index("alembic -c alembic-v2.ini check")

    assert "set -euo pipefail" in script
    assert upgrade < current < drift


def test_policy_data_qualification_precedes_schema_upgrade() -> None:
    workflow = _read(".github/workflows/seed-v2-database.yml")

    isolation = workflow.index("validate_database_environment.sh supabase")
    qualification = workflow.index("scripts/qualify_v2_policy_migration.py")
    upgrade = workflow.index("migrate_v2_metadata_schema.sh")

    assert isolation < qualification < upgrade


def test_household_data_qualification_precedes_schema_upgrade() -> None:
    workflow = _read(".github/workflows/seed-v2-database.yml")

    isolation = workflow.index("validate_database_environment.sh supabase")
    policy_qualification = workflow.index("scripts/qualify_v2_policy_migration.py")
    household_qualification = workflow.index(
        "scripts/qualify_v2_household_migration.py"
    )
    upgrade = workflow.index("migrate_v2_metadata_schema.sh")

    assert isolation < policy_qualification < household_qualification < upgrade


def test_user_association_qualification_precedes_schema_upgrade() -> None:
    workflow = _read(".github/workflows/seed-v2-database.yml")

    household_qualification = workflow.index(
        "scripts/qualify_v2_household_migration.py"
    )
    user_association_qualification = workflow.index(
        "scripts/qualify_v2_user_association_migration.py"
    )
    upgrade = workflow.index("migrate_v2_metadata_schema.sh")

    assert household_qualification < user_association_qualification < upgrade


def test_declared_privileges_are_granted_and_verified_before_catalog_seeding() -> None:
    workflow = _read(".github/workflows/seed-v2-database.yml")

    upgrade = workflow.index("migrate_v2_metadata_schema.sh")
    grant = workflow.index("scripts/reconcile_v2_privileges.py apply")
    verify = workflow.index("scripts/reconcile_v2_privileges.py verify")
    catalog_seed = workflow.index("scripts/publish_v2_metadata_catalog.py")

    assert upgrade < grant < verify < catalog_seed
    assert "--create-missing-roles" not in workflow


def test_privilege_steps_connect_with_the_migration_credential() -> None:
    workflow = _read(".github/workflows/seed-v2-database.yml")
    grant = _step(
        workflow,
        "Grant declared v2 table privileges",
        "Verify declared v2 table privileges",
    )
    verify = _step(
        workflow,
        "Verify declared v2 table privileges",
        "Seed and validate the v2 metadata catalog",
    )

    for step in (grant, verify):
        assert (
            "V2_MIGRATION_DATABASE_URL: ${{ secrets.V2_MIGRATION_DATABASE_URL }}"
            in step
        )
        assert "V2_DATA_WRITE_DATABASE_URL" not in step
    assert "DEPLOYMENT_ENVIRONMENT: ${{ inputs.deployment_environment }}" in _job(
        workflow, "seed"
    )


def test_seeding_success_is_required_before_candidate_creation() -> None:
    jobs = push_workflow_jobs()

    for environment, database_jobs in DATABASE_JOBS_BY_ENVIRONMENT.items():
        seeding = jobs[database_jobs["v2_seeding"]]
        candidate_deploy = jobs[database_jobs["candidate_deploy"]]

        assert seeding["with"] == {"deployment_environment": environment}
        assert seeding["secrets"] == "inherit"
        # The candidate deploy waits for both database jobs.
        assert database_jobs["v2_seeding"] in job_needs(candidate_deploy)
        assert database_jobs["v1_upgrade"] in job_needs(candidate_deploy)


def test_v1_upgrade_and_v2_seeding_run_side_by_side() -> None:
    # Neither job reads the other's database: the v1 upgrade connects only to
    # Cloud SQL through its proxy, and the seeding job only to the v2 database,
    # with no Cloud SQL proxy or v1 credentials.
    jobs = push_workflow_jobs()

    for environment, database_jobs in DATABASE_JOBS_BY_ENVIRONMENT.items():
        v1_upgrade = jobs[database_jobs["v1_upgrade"]]
        seeding = jobs[database_jobs["v2_seeding"]]

        assert database_jobs["v1_upgrade"] not in job_needs(seeding), environment
        assert database_jobs["v2_seeding"] not in job_needs(v1_upgrade), environment
        assert database_jobs["start_after"] in job_needs(seeding), environment
        assert database_jobs["start_after"] in job_needs(v1_upgrade), environment
        # Each keeps the GitHub environment it reads its database target from.
        assert v1_upgrade["with"] == {
            "deployment_environment": environment,
            "github_environment": f"{environment}-database",
        }
        assert v1_upgrade["secrets"] == "inherit"


def test_stage_9_deployment_shell_script_is_syntax_valid() -> None:
    result = subprocess.run(
        ["bash", "-n", ".github/scripts/migrate_v2_metadata_schema.sh"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
