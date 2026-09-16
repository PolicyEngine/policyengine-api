from __future__ import annotations

import pytest

from scripts.provision_stage12_database_runtime import (
    ProvisioningConfig,
    Stage12DatabaseProvisioningError,
    build_database_urls,
)

PROJECT_REF = "abcdefghijklmnopqrst"
BASE_URL = (
    "postgresql+psycopg://policyengine_v2_runtime.abcdefghijklmnopqrst:password@"
    "aws-0-us-east-2.pooler.supabase.com:5432/postgres?sslmode=require"
)


def config(**overrides) -> ProvisioningConfig:
    values = {
        "environment": "staging",
        "project_ref": PROJECT_REF,
        "source_secret_project": "policyengine-api",
        "base_runtime_url_secret": "v2-staging-runtime-url",
        "migration_password_secret": "v2-staging-migration-password",
        "owner_password_secret": "v2-staging-owner-password",
        "runtime_role": "policyengine_stage12_staging",
        "runtime_secret_project": "policyengine-simulation-entry",
        "runtime_secret_name": "stage12-staging-database-url",
        "secret_accessors": (
            "sim-entry-beta-runtime@policyengine-simulation-entry.iam.gserviceaccount.com",
            "sim-entry-gh-deployer@policyengine-simulation-entry.iam.gserviceaccount.com",
        ),
    }
    values.update(overrides)
    return ProvisioningConfig(**values)


def test_configuration_is_environment_bounded() -> None:
    config().validate()

    with pytest.raises(Stage12DatabaseProvisioningError, match="environment"):
        config(environment="beta").validate()
    with pytest.raises(Stage12DatabaseProvisioningError, match="identify"):
        config(runtime_role="policyengine_stage12_production").validate()


def test_database_urls_preserve_target_and_separate_credentials() -> None:
    urls = build_database_urls(
        base_runtime_url=BASE_URL,
        migration_password="migration-password",
        owner_password="owner-password",
        runtime_role="policyengine_stage12_staging",
        runtime_password="runtime-password",
        project_ref=PROJECT_REF,
        environment="staging",
    )

    assert urls.owner.username == f"postgres.{PROJECT_REF}"
    assert urls.migration.username == f"policyengine_v2_migrator.{PROJECT_REF}"
    assert urls.runtime.username == f"policyengine_stage12_staging.{PROJECT_REF}"
    assert urls.owner.password == "owner-password"
    assert urls.migration.password == "migration-password"
    assert urls.runtime.password == "runtime-password"
    assert urls.runtime.host == "aws-0-us-east-2.pooler.supabase.com"
    assert urls.runtime.port == 5432
    assert urls.runtime.database == "postgres"
    assert urls.runtime.query["sslmode"] == "require"


def test_database_urls_reject_another_supabase_target() -> None:
    with pytest.raises(Exception, match="project"):
        build_database_urls(
            base_runtime_url=BASE_URL,
            migration_password="migration-password",
            owner_password="owner-password",
            runtime_role="policyengine_stage12_staging",
            runtime_password="runtime-password",
            project_ref="zyxwvutsrqponmlkjihg",
            environment="staging",
        )
