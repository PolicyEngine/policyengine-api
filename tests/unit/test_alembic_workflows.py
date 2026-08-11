from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> str:
    return (REPO / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_pr_runs_reusable_alembic_check_only_for_relevant_changes():
    workflow = _workflow("pr.yml")

    assert "detect-v1-alembic-changes:" in workflow
    assert "python scripts/v1_alembic_changes.py" in workflow
    assert "alembic-v1-check:" in workflow
    assert "needs.detect-v1-alembic-changes.outputs.changed == 'true'" in workflow
    assert "uses: ./.github/workflows/alembic-v1-check.yml" in workflow


def test_push_always_runs_lint_and_alembic_qualification_before_versioning():
    workflow = _workflow("push.yml")

    assert "lint:" in workflow
    assert "alembic-v1-check:" in workflow
    assert "uses: ./.github/workflows/alembic-v1-check.yml" in workflow
    assert "needs: [lint, alembic-v1-check]" in workflow
    assert "github.repository == 'PolicyEngine/policyengine-uk'" not in workflow


def test_release_migration_uses_the_installed_python_environment():
    workflow = _workflow("push.yml")
    migration_job = workflow[workflow.index("  migrate-v1-cloud-sql:") :]
    migration_job = migration_job[: migration_job.index("\n  deploy-staging:")]

    assert "python scripts/write_v1_database_urls.py" in migration_job
    assert "python scripts/v1_database_migration.py" in migration_job
    assert "uv run" not in migration_job


def test_reusable_alembic_check_uses_only_disposable_mysql():
    workflow = _workflow("alembic-v1-check.yml")

    assert "workflow_call:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "mysql:8.4" in workflow
    assert "policyengine_alembic_test" in workflow
    assert "alembic-v1.ini" in workflow
    assert "STAGE7_EXISTING_DATABASE_URL" not in workflow
    assert "POLICYENGINE_DB_MIGRATION_PASSWORD" not in workflow


def test_reusable_alembic_check_uses_the_installed_python_environment():
    workflow = _workflow("alembic-v1-check.yml")

    assert "python -m pytest" in workflow
    assert "python -m alembic" in workflow
    assert "uv run" not in workflow


def test_release_migration_fails_closed_and_gates_both_staging_deploys():
    workflow = _workflow("push.yml")

    assert "migrate-v1-cloud-sql:" in workflow
    assert "environment: production-database" in workflow
    assert "--mode state" in workflow
    assert "--mode upgrade" in workflow
    assert "--mode verify-head" in workflow
    assert "database is unversioned" in workflow

    app_engine_job = workflow[workflow.index("  deploy-staging:") :]
    app_engine_job = app_engine_job[
        : app_engine_job.index("\n  deploy-cloud-run-staging:")
    ]
    assert "migrate-v1-cloud-sql" in app_engine_job

    cloud_run_job = workflow[workflow.index("  deploy-cloud-run-staging:") :]
    cloud_run_job = cloud_run_job[
        : cloud_run_job.index("\n  integration-tests-staging:")
    ]
    assert "migrate-v1-cloud-sql" in cloud_run_job


def test_cloud_sql_workflow_uses_oidc_and_separate_database_credentials():
    workflow = _workflow("push.yml")
    migration_job = workflow[workflow.index("  migrate-v1-cloud-sql:") :]
    migration_job = migration_job[: migration_job.index("\n  deploy-staging:")]

    assert "google-github-actions/auth@v2" in migration_job
    assert "GCP_DB_MIGRATION_SERVICE_ACCOUNT" in migration_job
    assert "policyengine-api-prod-db-readonly-password" in migration_job
    assert "policyengine-api-prod-db-migration-password" in migration_job
    assert "secrets.POLICYENGINE_DB_READONLY_PASSWORD" not in migration_job
    assert "secrets.POLICYENGINE_DB_MIGRATION_PASSWORD" not in migration_job
    assert (
        "POLICYENGINE_DB_PASSWORD: ${{ secrets.POLICYENGINE_DB_PASSWORD }}"
        not in migration_job
    )


def test_backup_helper_recovers_and_verifies_the_created_backup_id():
    script = (REPO / ".github" / "scripts" / "create_cloud_sql_backup.sh").read_text(
        encoding="utf-8"
    )

    assert "GITHUB_RUN_ID" in script
    assert "gcloud sql backups create" in script
    assert "gcloud sql backups list" in script
    assert "status=SUCCESSFUL" in script
    assert script.index("gcloud sql backups create") < script.index(
        "gcloud sql backups list"
    )


def test_v1_and_future_v2_alembic_domains_are_explicitly_separate():
    assert (REPO / "alembic-v1.ini").exists()
    assert (REPO / "migrations" / "v1" / "env.py").exists()

    guidance = REPO / "docs" / "engineering" / "skills" / "alembic-migrations.md"
    text = guidance.read_text(encoding="utf-8")
    assert "alembic-v1.ini" in text
    assert "migrations/v1" in text
    assert "Supabase/Postgres" in text
    assert "separate revision chain" in text
