"""Tests for .github/scripts/run_household_mirror_event_operator.sh.

The script validates the source and destination databases and the operator
identity, fetches the Cloud SQL migration password, and runs the event command
through ``uv run --frozen``. Fake ``gcloud`` and ``uv`` commands first on
``PATH`` record what they were called with and the environment ``uv`` received.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / ".github/scripts/run_household_mirror_event_operator.sh"
OPERATOR_IDENTITY = "household-operator@policyengine-api.iam.gserviceaccount.com"
STAGING_MIGRATION_PASSWORD = "staging-migrator-p@ss"
STAGING_V2_WRITE_URL = (
    "postgresql+psycopg://writer:writer-p%40ss@staging.example.test:6543/postgres"
)
EVENT_ARGUMENTS = (
    "--environment",
    "staging",
    "--country-id",
    "us",
    "--legacy-household-id",
    "12345",
)
# The variables the event command reads: the ones this script sets and the
# job-level ones the workflow declares.
FORWARDED_VARIABLES = (
    "POLICYENGINE_DB_PROXY_PORT",
    "POLICYENGINE_DB_PASSWORD",
    "DEPLOYMENT_ENVIRONMENT",
    "V2_SUPABASE_ENVIRONMENT",
    "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME",
    "PRODUCTION_POLICYENGINE_DB_INSTANCE_CONNECTION_NAME",
    "V2_SUPABASE_PROJECT_REF",
    "PRODUCTION_V2_SUPABASE_PROJECT_REF",
    "V2_RUNTIME_DATABASE_URL",
    "HOUSEHOLD_MIRROR_OPERATOR_IDENTITY",
    "ALLOWED_HOUSEHOLD_MIRROR_OPERATOR_IDENTITY",
)


def _staging_environment(**overrides: str) -> dict[str, str]:
    """Return the job-level environment the workflow sets for staging."""
    environment = {
        "DEPLOYMENT_ENVIRONMENT": "staging",
        "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": (
            "policyengine-api:us-central1:staging-instance"
        ),
        "PRODUCTION_POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": (
            "policyengine-api:us-central1:production-instance"
        ),
        "POLICYENGINE_DB_MIGRATION_PASSWORD_SECRET": "staging-migration-password",
        "PRODUCTION_POLICYENGINE_DB_MIGRATION_PASSWORD_SECRET": (
            "production-migration-password"
        ),
        "POLICYENGINE_DB_READONLY_PASSWORD_SECRET": "staging-readonly-password",
        "PRODUCTION_POLICYENGINE_DB_READONLY_PASSWORD_SECRET": (
            "production-readonly-password"
        ),
        "V2_SUPABASE_PROJECT_REF": "stagingprojectref000",
        "V2_SUPABASE_ENVIRONMENT": "staging",
        "PRODUCTION_V2_SUPABASE_PROJECT_REF": "productionprojectref",
        "V2_RUNTIME_DATABASE_URL": STAGING_V2_WRITE_URL,
        "HOUSEHOLD_MIRROR_OPERATOR_IDENTITY": OPERATOR_IDENTITY,
        "ALLOWED_HOUSEHOLD_MIRROR_OPERATOR_IDENTITY": OPERATOR_IDENTITY,
        "GITHUB_ACTIONS": "true",
    }
    environment.update(overrides)
    return environment


def _write_fake_commands(tmp_path: Path, *, migration_password: str) -> Path:
    """Write fake gcloud and uv commands that record their calls."""
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    gcloud_path = bin_path / "gcloud"
    gcloud_path.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "${GCLOUD_CALLS}"\n'
        f'printf "%s\\n" "{migration_password}"\n',
        encoding="utf-8",
    )
    gcloud_path.chmod(0o755)
    recorded_variables = "".join(
        f'printf "%s=%s\\n" "{variable_name}" "${{{variable_name}-<unset>}}" '
        '>> "${UV_ENVIRONMENT}"\n'
        for variable_name in FORWARDED_VARIABLES
    )
    uv_path = bin_path / "uv"
    uv_path.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "${UV_CALLS}"\n' + recorded_variables,
        encoding="utf-8",
    )
    uv_path.chmod(0o755)
    return bin_path


def _run_operator(
    tmp_path: Path,
    environment: dict[str, str],
    *,
    migration_password: str = STAGING_MIGRATION_PASSWORD,
) -> tuple[subprocess.CompletedProcess[str], list[str], list[str], dict[str, str]]:
    bin_path = _write_fake_commands(tmp_path, migration_password=migration_password)
    gcloud_calls = tmp_path / "gcloud-calls"
    uv_calls = tmp_path / "uv-calls"
    uv_environment = tmp_path / "uv-environment"
    result = subprocess.run(
        ["bash", str(SCRIPT), *EVENT_ARGUMENTS],
        cwd=REPO,
        env={
            "HOME": os.environ.get("HOME", ""),
            "PATH": f"{bin_path}{os.pathsep}{os.environ['PATH']}",
            "GCLOUD_CALLS": str(gcloud_calls),
            "UV_CALLS": str(uv_calls),
            "UV_ENVIRONMENT": str(uv_environment),
            **environment,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    def recorded(path: Path) -> list[str]:
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    received = dict(
        recorded_line.split("=", 1) for recorded_line in recorded(uv_environment)
    )
    return result, recorded(gcloud_calls), recorded(uv_calls), received


def test_runs_the_event_command_through_the_lock_with_the_fetched_password(
    tmp_path,
):
    environment = _staging_environment()

    result, gcloud_calls, uv_calls, received = _run_operator(tmp_path, environment)

    assert result.returncode == 0, result.stderr
    assert gcloud_calls == [
        "secrets versions access latest --secret staging-migration-password "
        "--project policyengine-api"
    ]
    assert uv_calls == [
        "run --frozen python scripts/process_v1_household_mirror_event.py "
        + " ".join(EVENT_ARGUMENTS)
    ]
    assert f"::add-mask::{STAGING_MIGRATION_PASSWORD}" in result.stdout
    assert received["POLICYENGINE_DB_PROXY_PORT"] == "3307"
    assert received["POLICYENGINE_DB_PASSWORD"] == STAGING_MIGRATION_PASSWORD
    for variable_name in FORWARDED_VARIABLES[2:]:
        assert received[variable_name] == environment[variable_name], variable_name


def test_refuses_an_unauthorized_operator_before_fetching_the_password(tmp_path):
    environment = _staging_environment(
        HOUSEHOLD_MIRROR_OPERATOR_IDENTITY="other@policyengine-api.iam.gserviceaccount.com"
    )

    result, gcloud_calls, uv_calls, _ = _run_operator(tmp_path, environment)

    assert result.returncode == 1
    assert "not authorized for household event processing" in result.stderr
    assert gcloud_calls == []
    assert uv_calls == []


def test_refuses_staging_that_targets_the_production_database(tmp_path):
    environment = _staging_environment(
        POLICYENGINE_DB_INSTANCE_CONNECTION_NAME=(
            "policyengine-api:us-central1:production-instance"
        )
    )

    result, gcloud_calls, uv_calls, _ = _run_operator(tmp_path, environment)

    assert result.returncode == 1
    assert "distinct from production" in result.stderr
    assert gcloud_calls == []
    assert uv_calls == []


def test_refuses_an_empty_migration_password(tmp_path):
    result, gcloud_calls, uv_calls, _ = _run_operator(
        tmp_path, _staging_environment(), migration_password=""
    )

    assert result.returncode == 1
    assert "must not be empty" in result.stderr
    assert len(gcloud_calls) == 1
    assert uv_calls == []
