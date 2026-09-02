from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


REPO = Path(__file__).resolve().parents[2]


def _workflow(name: str) -> str:
    return (REPO / ".github" / "workflows" / name).read_text(encoding="utf-8")


def _long_inline_run_blocks() -> list[str]:
    offenders = []
    block_markers = {"|", "|-", "|+", ">", ">-", ">+"}
    for path in sorted((REPO / ".github" / "workflows").glob("*.y*ml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        line_index = 0
        while line_index < len(lines):
            line = lines[line_index]
            stripped = line.lstrip()
            indentation = len(line) - len(stripped)
            if not (
                stripped.startswith("run:")
                and stripped.removeprefix("run:").strip() in block_markers
            ):
                line_index += 1
                continue

            body_start = line_index + 1
            line_index = body_start
            while line_index < len(lines):
                candidate = lines[line_index]
                candidate_indentation = len(candidate) - len(candidate.lstrip())
                if candidate.strip() and candidate_indentation <= indentation:
                    break
                line_index += 1

            substantive_lines = [
                candidate
                for candidate in lines[body_start:line_index]
                if candidate.strip() and not candidate.lstrip().startswith("#")
            ]
            if len(substantive_lines) > 3:
                offenders.append(f"{path.name}:{body_start}")
    return offenders


def test_workflows_do_not_inline_long_shell_programs():
    assert _long_inline_run_blocks() == []


def test_pr_always_runs_reusable_alembic_and_v2_integration_checks():
    workflow = _workflow("pr.yml")
    alembic_job = workflow[workflow.index("  alembic-v2-check:") :]
    alembic_job = alembic_job[: alembic_job.index("\n  v2-integration-check:")]
    integration_job = workflow[workflow.index("  v2-integration-check:") :]
    integration_job = integration_job[: integration_job.index("\n  check-changelog:")]

    assert "alembic-v1-check:" in workflow
    assert "uses: ./.github/workflows/alembic-v1-check.yml" in workflow
    assert "detect-v1-alembic-changes:" not in workflow
    assert "needs.detect-v1-alembic-changes" not in workflow
    assert "detect-v2-platform-changes:" not in workflow
    assert "dorny/paths-filter" not in workflow
    assert "alembic-v2-check:" in workflow
    assert "uses: ./.github/workflows/alembic-v2-check.yml" in alembic_job
    assert "CODECOV_TOKEN" not in alembic_job
    assert "v2-integration-check:" in workflow
    assert "uses: ./.github/workflows/v2-integration-check.yml" in integration_job
    assert "CODECOV_TOKEN: ${{ secrets.CODECOV_TOKEN }}" in integration_job
    assert "needs:" not in alembic_job
    assert "if:" not in alembic_job
    assert "needs:" not in integration_job
    assert "if:" not in integration_job


def test_push_requires_schema_and_v2_integration_checks_before_versioning():
    workflow = _workflow("push.yml")
    versioning_job = workflow[workflow.index("  versioning:") :]
    versioning_job = versioning_job[: versioning_job.index("\n  publish-git-tag:")]
    tag_job = workflow[workflow.index("  publish-git-tag:") :]
    tag_job = tag_job[: tag_job.index("\n  migrate-v1-cloud-sql:")]

    assert "lint:" in workflow
    assert "alembic-v1-check:" in workflow
    assert "uses: ./.github/workflows/alembic-v1-check.yml" in workflow
    assert "alembic-v2-check:" in workflow
    assert "uses: ./.github/workflows/alembic-v2-check.yml" in workflow
    assert "v2-integration-check:" in workflow
    assert "uses: ./.github/workflows/v2-integration-check.yml" in workflow
    assert "CODECOV_TOKEN: ${{ secrets.CODECOV_TOKEN }}" in workflow
    for required_job in (
        "lint",
        "alembic-v1-check",
        "alembic-v2-check",
        "v2-integration-check",
    ):
        assert f"- {required_job}" in versioning_job
        assert f"- {required_job}" in tag_job
    assert "github.repository == 'PolicyEngine/policyengine-uk'" not in workflow


def test_release_migration_uses_the_installed_python_environment():
    workflow = _workflow("push.yml")
    migration_job = workflow[workflow.index("  migrate-v1-cloud-sql:") :]
    migration_job = migration_job[
        : migration_job.index("\n  deploy-cloud-run-staging:")
    ]
    orchestration_script = (
        REPO / ".github" / "scripts" / "migrate_v1_cloud_sql.sh"
    ).read_text(encoding="utf-8")

    assert "bash .github/scripts/migrate_v1_cloud_sql.sh" in migration_job
    assert "python scripts/v1_database_migration.py" in orchestration_script
    assert "uv run" not in orchestration_script


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


def test_reusable_v2_alembic_check_uses_only_disposable_postgres():
    workflow = _workflow("alembic-v2-check.yml")
    lifecycle_script = (
        REPO / ".github" / "scripts" / "test_alembic_v2_lifecycle.sh"
    ).read_text(encoding="utf-8")

    assert "workflow_call:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "postgres:17" in workflow
    assert "V2_ALEMBIC_DISPOSABLE_TEST" in workflow
    assert "alembic-v2.ini" in workflow
    assert "bash .github/scripts/test_alembic_v2_lifecycle.sh" in workflow
    assert "test_alembic_v2.py" in lifecycle_script
    assert "test_alembic_v2_lifecycle.py" in lifecycle_script
    assert "redis:7.2-alpine" not in workflow
    assert "RUNTIME_CACHE_TEST_URL" not in workflow
    assert "test_v2_catalog_installed.py" not in workflow
    assert "test_v2_catalog_publication.py" not in workflow
    assert "test_v2_metadata_routes.py" not in workflow
    assert "test_v2_catalog_publication_qualification.py" not in workflow
    assert "test_runtime_cache_redis.py" not in workflow
    assert "coverage run" not in workflow
    assert "codecov/codecov-action" not in workflow


def test_reusable_v2_integration_check_uses_postgres_redis_and_coverage():
    workflow = _workflow("v2-integration-check.yml")

    assert "workflow_call:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "postgres:17" in workflow
    assert "redis:7.2-alpine" in workflow
    assert "V2_ALEMBIC_DISPOSABLE_TEST" in workflow
    assert "RUNTIME_CACHE_TEST_URL" in workflow
    assert "alembic -c alembic-v2.ini upgrade head" in workflow
    assert "test_alembic_v2_lifecycle.sh" not in workflow
    assert "test_v2_catalog_installed.py" in workflow
    assert "RUN_V2_CATALOG_COMPATIBILITY" in workflow
    assert "test_v2_catalog_publication.py" in workflow
    assert "test_v2_metadata_routes.py" in workflow
    assert "test_v2_policy_persistence.py" in workflow
    assert "test_v1_policy_dual_write.py" in workflow
    assert "test_v2_user_policy_mirroring.py" in workflow
    assert "test_v1_user_policy_dual_write.py" in workflow
    assert "test_v2_catalog_publication_qualification.py" in workflow
    assert "RUN_V2_CATALOG_PUBLICATION_QUALIFICATION" in workflow
    assert "test_runtime_cache_redis.py" in workflow
    assert "uv sync --frozen" in workflow
    assert workflow.count("coverage run --branch") == 1
    assert workflow.count("coverage run -a --branch") == 4
    assert "coverage xml -i -o coverage-v2.xml" in workflow
    assert "codecov/codecov-action@v5" in workflow
    assert "files: coverage-v2.xml" in workflow


def test_release_migration_fails_closed_before_tests_and_cloud_run_deploy():
    workflow = _workflow("push.yml")
    orchestration_script = (
        REPO / ".github" / "scripts" / "migrate_v1_cloud_sql.sh"
    ).read_text(encoding="utf-8")

    assert "migrate-v1-cloud-sql:" in workflow
    assert "environment: production-database" in workflow
    assert "--mode state" in orchestration_script
    assert "--mode upgrade" in orchestration_script
    assert "--mode verify-head" in orchestration_script
    assert "database is unversioned" in orchestration_script
    assert "create_cloud_sql_backup.sh" in orchestration_script

    cloud_run_job = workflow[workflow.index("  deploy-cloud-run-staging:") :]
    cloud_run_job = cloud_run_job[
        : cloud_run_job.index("\n  integration-tests-staging-cloud-run:")
    ]
    assert "migrate-v1-cloud-sql" in cloud_run_job
    assert "make test" in cloud_run_job
    assert cloud_run_job.index("make test") < cloud_run_job.index(
        'uses: "google-github-actions/auth@v2"'
    )
    assert cloud_run_job.index("make test") < cloud_run_job.index(
        "Build and push Cloud Run image"
    )


def test_cloud_sql_workflow_uses_oidc_and_separate_database_credentials():
    workflow = _workflow("push.yml")
    migration_job = workflow[workflow.index("  migrate-v1-cloud-sql:") :]
    migration_job = migration_job[
        : migration_job.index("\n  deploy-cloud-run-staging:")
    ]
    orchestration_script = (
        REPO / ".github" / "scripts" / "migrate_v1_cloud_sql.sh"
    ).read_text(encoding="utf-8")

    assert "google-github-actions/auth@v2" in migration_job
    assert "GCP_DB_MIGRATION_SERVICE_ACCOUNT" in migration_job
    assert "migrate_v1_cloud_sql.sh" in migration_job
    assert "prepare_v1_database_urls.sh" not in migration_job
    assert "GITHUB_ENV" not in orchestration_script
    assert "secrets.POLICYENGINE_DB_READONLY_PASSWORD" not in migration_job
    assert "secrets.POLICYENGINE_DB_MIGRATION_PASSWORD" not in migration_job
    assert (
        "POLICYENGINE_DB_PASSWORD: ${{ secrets.POLICYENGINE_DB_PASSWORD }}"
        not in migration_job
    )


def _write_fake_migration_commands(tmp_path: Path) -> tuple[Path, Path]:
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    gcloud_path = bin_path / "gcloud"
    gcloud_path.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "${GCLOUD_CALLS}"\n'
        'if [[ "$*" == *"readonly-password"* ]]; then\n'
        '  printf "reader-p@ss\\n"\n'
        'elif [[ "$*" == *"migration-password"* ]]; then\n'
        '  printf "migrator-p@ss\\n"\n'
        'elif [[ "$*" == *"sql backups list"* ]]; then\n'
        '  printf "backup-123\\n"\n'
        "fi\n",
        encoding="utf-8",
    )
    gcloud_path.chmod(0o755)

    python_path = bin_path / "python"
    python_path.write_text(
        "#!/usr/bin/env bash\n"
        ': "${POLICYENGINE_DB_READONLY_PASSWORD:?}"\n'
        ': "${POLICYENGINE_DB_MIGRATION_PASSWORD:?}"\n'
        'printf "%s\\n" "$*" >> "${PYTHON_CALLS}"\n'
        'if [[ "$*" == *"--mode state"* ]]; then\n'
        '  printf "%s\\n" "${DATABASE_STATE}"\n'
        "fi\n",
        encoding="utf-8",
    )
    python_path.chmod(0o755)
    return bin_path, gcloud_path


def _run_migration_orchestrator(tmp_path: Path, database_state: str):
    bin_path, _ = _write_fake_migration_commands(tmp_path)
    python_calls = tmp_path / "python-calls"
    gcloud_calls = tmp_path / "gcloud-calls"
    result = subprocess.run(
        ["bash", ".github/scripts/migrate_v1_cloud_sql.sh"],
        cwd=REPO,
        env={
            **os.environ,
            "DATABASE_STATE": database_state,
            "GCLOUD_CALLS": str(gcloud_calls),
            "PYTHON_CALLS": str(python_calls),
            "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": "project:region:instance",
            "PATH": f"{bin_path}:{os.environ['PATH']}",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return result, python_calls, gcloud_calls


def test_migration_orchestrator_keeps_credentials_local_and_upgrades_pending_schema(
    tmp_path,
):
    result, python_calls, gcloud_calls = _run_migration_orchestrator(
        tmp_path, "pending"
    )

    assert result.returncode == 0, result.stderr
    assert "::add-mask::reader-p@ss" in result.stdout
    assert "::add-mask::migrator-p@ss" in result.stdout
    assert "STAGE7_EXISTING_DATABASE_URL" not in result.stdout
    assert "ALEMBIC_DATABASE_URL" not in result.stdout
    calls = python_calls.read_text(encoding="utf-8").splitlines()
    assert calls == [
        "scripts/v1_database_migration.py --mode state",
        "scripts/v1_database_migration.py --mode upgrade --backup-id backup-123",
        "scripts/v1_database_migration.py --mode verify-head",
    ]
    assert "sql backups create" in gcloud_calls.read_text(encoding="utf-8")


def test_migration_orchestrator_skips_backup_and_upgrade_at_head(tmp_path):
    result, python_calls, gcloud_calls = _run_migration_orchestrator(tmp_path, "head")

    assert result.returncode == 0, result.stderr
    assert python_calls.read_text(encoding="utf-8").splitlines() == [
        "scripts/v1_database_migration.py --mode state",
        "scripts/v1_database_migration.py --mode verify-head",
    ]
    assert "sql backups create" not in gcloud_calls.read_text(encoding="utf-8")


@pytest.mark.parametrize("database_state", ["unversioned", "invalid"])
def test_migration_orchestrator_refuses_unsafe_database_states(
    tmp_path,
    database_state,
):
    result, python_calls, gcloud_calls = _run_migration_orchestrator(
        tmp_path, database_state
    )

    assert result.returncode != 0
    assert "automatic baseline stamping is disabled" in result.stderr
    assert python_calls.read_text(encoding="utf-8").splitlines() == [
        "scripts/v1_database_migration.py --mode state"
    ]
    assert "sql backups create" not in gcloud_calls.read_text(encoding="utf-8")


def test_backup_helper_recovers_and_verifies_the_created_backup_id():
    script = (REPO / ".github" / "scripts" / "create_cloud_sql_backup.sh").read_text(
        encoding="utf-8"
    )

    assert "GITHUB_RUN_ID" in script
    assert "gcloud sql backups create" in script
    assert "gcloud sql backups list" in script
    assert "status=SUCCESSFUL" in script
    assert "GITHUB_OUTPUT" not in script
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
