"""Deployment ordering and credential-isolation tests for Stage 9."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess


REPO = Path(__file__).resolve().parents[3]


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


def test_seeding_success_is_required_before_candidate_creation() -> None:
    workflow = _read(".github/workflows/push.yml")
    staging_seed = _job(workflow, "seed-v2-staging-database")
    production_seed = _job(workflow, "seed-v2-production-database")

    assert "deployment_environment: staging" in staging_seed
    assert "migrate-v1-cloud-sql" in staging_seed
    assert "seed-v2-staging-database" in _job(
        workflow,
        "deploy-cloud-run-staging",
    )

    assert (
        "needs: ensure-production-model-version-aligns-with-sim-api" in production_seed
    )
    assert "deployment_environment: production" in production_seed
    assert "needs: seed-v2-production-database" in _job(
        workflow,
        "deploy-cloud-run-candidate",
    )


def test_stage_9_deployment_shell_script_is_syntax_valid() -> None:
    result = subprocess.run(
        ["bash", "-n", ".github/scripts/migrate_v2_metadata_schema.sh"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
