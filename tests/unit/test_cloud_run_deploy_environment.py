"""Validation of the environment a Cloud Run deployment runs with."""

from __future__ import annotations

import pytest

from tests.unit.cloud_run_deploy_support import (
    PRODUCTION_CLOUD_SQL_INSTANCE,
    PRODUCTION_DB_PASSWORD_SECRET,
    TEST_AUTH0_SECRET_RESOURCE,
    TEST_V2_PROJECT_REF,
    TEST_V2_RUNTIME_SECRET_RESOURCE,
)
from tests.unit.cloud_run_deploy_support import (
    gateway_auth_env as _gateway_auth_env,
)
from tests.unit.cloud_run_deploy_support import (
    observability_env as _observability_env,
)
from tests.unit.cloud_run_deploy_support import (
    public_api_auth_env as _public_api_auth_env,
)
from tests.unit.cloud_run_deploy_support import (
    required_runtime_env as _required_runtime_env,
)
from tests.unit.cloud_run_deploy_support import (
    run_script as _run_script,
)
from tests.unit.cloud_run_deploy_support import (
    script_env as _script_env,
)
from tests.unit.cloud_run_deploy_support import (
    v2_target_env as _v2_target_env,
)


def test_validate_cloud_run_deploy_env_requires_selector_environment_variable():
    env = _script_env(**_required_runtime_env())
    env.pop("SIM_ENTRYPOINT")
    env.pop("SIMULATION_ENTRYPOINT_URL")
    result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        env,
    )

    assert result.returncode == 1
    assert "SIM_ENTRYPOINT" in result.stderr


def test_validate_cloud_run_deploy_env_accepts_direct_mode_from_environment():
    result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        _script_env(
            SIM_ENTRYPOINT="old_gateway_direct",
            OLD_SIMULATION_GATEWAY_URL="https://old-gateway.example.test",
            ROUTE_IMPL_HEALTH="fastapi_native",
            ROUTE_IMPL_SPECIFICATION="fastapi_native",
            ROUTE_IMPL_METADATA="fastapi_native",
            ROUTE_IMPL_POLICY="flask_fallback",
            ROUTE_IMPL_HOUSEHOLD="flask_fallback",
            DB_READ_POLICY="cloud_sql",
            DB_WRITE_POLICY="cloud_sql",
            DB_READ_HOUSEHOLD="cloud_sql",
            DB_WRITE_HOUSEHOLD="cloud_sql",
            POLICYENGINE_DB_INSTANCE_CONNECTION_NAME=PRODUCTION_CLOUD_SQL_INSTANCE,
            DEPLOYMENT_ENVIRONMENT="production",
            PRODUCTION_POLICYENGINE_DB_INSTANCE_CONNECTION_NAME=(
                PRODUCTION_CLOUD_SQL_INSTANCE
            ),
            PRODUCTION_V2_SUPABASE_PROJECT_REF=TEST_V2_PROJECT_REF,
            PRODUCTION_V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE=(
                TEST_V2_RUNTIME_SECRET_RESOURCE
            ),
            PRODUCTION_CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET=(
                PRODUCTION_DB_PASSWORD_SECRET
            ),
            CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET=PRODUCTION_DB_PASSWORD_SECRET,
            **_v2_target_env(),
            **_gateway_auth_env(),
            **_public_api_auth_env(),
            **_observability_env(),
        ),
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "missing_selector",
    [
        "ROUTE_IMPL_HEALTH",
        "ROUTE_IMPL_SPECIFICATION",
        "ROUTE_IMPL_METADATA",
        "ROUTE_IMPL_POLICY",
        "ROUTE_IMPL_HOUSEHOLD",
        "DB_READ_POLICY",
        "DB_WRITE_POLICY",
        "DB_READ_HOUSEHOLD",
        "DB_WRITE_HOUSEHOLD",
    ],
)
def test_validate_cloud_run_deploy_env_requires_migration_selectors(missing_selector):
    env = _script_env(**_required_runtime_env())
    env.pop(missing_selector)

    result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        env,
    )

    assert result.returncode == 1
    assert missing_selector in result.stderr


@pytest.mark.parametrize(
    "invalid_selector",
    [
        "ROUTE_IMPL_HEALTH",
        "ROUTE_IMPL_SPECIFICATION",
        "ROUTE_IMPL_METADATA",
        "ROUTE_IMPL_POLICY",
    ],
)
def test_validate_cloud_run_deploy_env_rejects_invalid_route_selectors(
    invalid_selector,
):
    env = _script_env(**_required_runtime_env())
    env[invalid_selector] = "sometimes_native"

    result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        env,
    )

    assert result.returncode == 1
    assert (
        f"{invalid_selector}=sometimes_native is invalid; expected "
        "flask_fallback or fastapi_native"
    ) in result.stderr


@pytest.mark.parametrize("invalid_value", ["fastapi_native", "sometimes_native"])
def test_validate_cloud_run_deploy_env_requires_household_flask_fallback(
    invalid_value,
):
    env = _script_env(**_required_runtime_env())
    env["ROUTE_IMPL_HOUSEHOLD"] = invalid_value

    result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        env,
    )

    assert result.returncode == 1
    assert (
        f"ROUTE_IMPL_HOUSEHOLD={invalid_value} is invalid; expected "
        "flask_fallback during Stage 11"
    ) in result.stderr


@pytest.mark.parametrize(
    ("selector", "invalid_value", "expected_values"),
    [
        ("DB_READ_POLICY", "supabase", "cloud_sql"),
        ("DB_WRITE_POLICY", "supabase", "cloud_sql or dual_write"),
        ("DB_READ_HOUSEHOLD", "supabase", "cloud_sql"),
        ("DB_WRITE_HOUSEHOLD", "supabase", "cloud_sql or dual_write"),
    ],
)
def test_validate_cloud_run_deploy_env_rejects_invalid_policy_database_selectors(
    selector,
    invalid_value,
    expected_values,
):
    env = _script_env(**_required_runtime_env())
    env[selector] = invalid_value

    result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        env,
    )

    assert result.returncode == 1
    assert (
        f"{selector}={invalid_value} is invalid; expected {expected_values}"
        in result.stderr
    )


@pytest.mark.parametrize(
    ("entrypoint", "selected_url_env", "selected_url"),
    [
        (
            "old_gateway_direct",
            "OLD_SIMULATION_GATEWAY_URL",
            "https://old-gateway.example.test",
        ),
        (
            "cloud_run_simulation_entrypoint",
            "SIMULATION_ENTRYPOINT_URL",
            "https://simulation.example.test",
        ),
    ],
)
def test_validate_cloud_run_deploy_env_requires_only_selected_url(
    entrypoint,
    selected_url_env,
    selected_url,
):
    env = _script_env(
        SIM_ENTRYPOINT=entrypoint,
        ROUTE_IMPL_HEALTH="fastapi_native",
        ROUTE_IMPL_SPECIFICATION="fastapi_native",
        ROUTE_IMPL_METADATA="fastapi_native",
        ROUTE_IMPL_POLICY="flask_fallback",
        ROUTE_IMPL_HOUSEHOLD="flask_fallback",
        DB_READ_POLICY="cloud_sql",
        DB_WRITE_POLICY="cloud_sql",
        DB_READ_HOUSEHOLD="cloud_sql",
        DB_WRITE_HOUSEHOLD="cloud_sql",
        POLICYENGINE_DB_INSTANCE_CONNECTION_NAME=PRODUCTION_CLOUD_SQL_INSTANCE,
        DEPLOYMENT_ENVIRONMENT="production",
        PRODUCTION_POLICYENGINE_DB_INSTANCE_CONNECTION_NAME=(
            PRODUCTION_CLOUD_SQL_INSTANCE
        ),
        PRODUCTION_V2_SUPABASE_PROJECT_REF=TEST_V2_PROJECT_REF,
        PRODUCTION_V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE=(
            TEST_V2_RUNTIME_SECRET_RESOURCE
        ),
        PRODUCTION_CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET=(
            PRODUCTION_DB_PASSWORD_SECRET
        ),
        CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET=PRODUCTION_DB_PASSWORD_SECRET,
        **_v2_target_env(),
        **_gateway_auth_env(),
        **_public_api_auth_env(),
        **_observability_env(),
    )
    missing_result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        env,
    )
    valid_result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        {**env, selected_url_env: selected_url},
    )

    assert missing_result.returncode == 1
    assert selected_url_env in missing_result.stderr
    assert valid_result.returncode == 0, valid_result.stderr


@pytest.mark.parametrize(
    "missing_name",
    [
        "V2_SUPABASE_PROJECT_REF",
        "V2_SUPABASE_ENVIRONMENT",
    ],
)
def test_deployment_validation_requires_supabase_target_variables(
    missing_name,
):
    env = _script_env(**_required_runtime_env())
    env.pop(missing_name)

    result = _run_script(".github/scripts/validate_cloud_run_deploy_env.sh", env)

    assert result.returncode == 1
    assert missing_name in result.stderr


def test_cloud_run_requires_v2_runtime_database_configuration():
    env = _script_env(**_required_runtime_env())
    env.pop("V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE")

    cloud_run = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        env,
    )

    assert cloud_run.returncode == 1
    assert "V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE" in cloud_run.stderr


def test_deployment_validation_requires_database_instance_connection_name():
    env = _script_env(**_required_runtime_env())
    env.pop("POLICYENGINE_DB_INSTANCE_CONNECTION_NAME")

    result = _run_script(".github/scripts/validate_cloud_run_deploy_env.sh", env)

    assert result.returncode == 1
    assert "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME" in result.stderr


def _staging_runtime_env() -> dict[str, str]:
    return {
        **_required_runtime_env(),
        "DEPLOYMENT_ENVIRONMENT": "staging",
        "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": (
            "policyengine-api:us-central1:policyengine-api-data-staging"
        ),
        "CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET": (
            "policyengine-api-staging-db-password:latest"
        ),
        "V2_SUPABASE_PROJECT_REF": "z" * 20,
        "V2_SUPABASE_ENVIRONMENT": "staging",
        "V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE": (
            "projects/test-project/secrets/v2-staging-runtime-url/versions/latest"
        ),
    }


def test_deployment_validation_accepts_distinct_staging_database_targets():
    result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        _script_env(**_staging_runtime_env()),
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("setting", "production_setting"),
    [
        (
            "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME",
            "PRODUCTION_POLICYENGINE_DB_INSTANCE_CONNECTION_NAME",
        ),
        ("V2_SUPABASE_PROJECT_REF", "PRODUCTION_V2_SUPABASE_PROJECT_REF"),
        (
            "CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET",
            "PRODUCTION_CLOUD_RUN_POLICYENGINE_DB_PASSWORD_SECRET",
        ),
        (
            "V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE",
            "PRODUCTION_V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE",
        ),
    ],
)
def test_deployment_validation_rejects_shared_staging_database_targets(
    setting,
    production_setting,
):
    env = _staging_runtime_env()
    env[setting] = env[production_setting]

    result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh",
        _script_env(**env),
    )

    assert result.returncode == 1
    assert "distinct from production" in result.stderr


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"PUBLIC_API_AUTH_REQUIRED": None}, "PUBLIC_API_AUTH_REQUIRED"),
        ({"PUBLIC_API_AUTH_REQUIRED": "true"}, "expected 0 or 1"),
        ({"PUBLIC_API_AUTH_ISSUER": None}, "PUBLIC_API_AUTH_ISSUER"),
        ({"PUBLIC_API_AUTH_AUDIENCE": None}, "PUBLIC_API_AUTH_AUDIENCE"),
        (
            {"PUBLIC_API_AUTH_REQUIRED": "0", "PUBLIC_API_AUTH_AUDIENCE": None},
            "or neither",
        ),
        ({"PUBLIC_API_AUTH_ISSUER": "http://auth.example.test/"}, "HTTPS"),
        ({"AUTH0_MANAGEMENT_DOMAIN": "policyengine.us.auth0.com"}, "or none"),
    ],
)
def test_validate_cloud_run_deploy_env_rejects_unsafe_user_auth_settings(
    changes, message
):
    env = _script_env(**_required_runtime_env())
    for name, value in changes.items():
        if value is None:
            env.pop(name)
        else:
            env[name] = value

    result = _run_script(".github/scripts/validate_cloud_run_deploy_env.sh", env)

    assert result.returncode == 1
    assert message in result.stderr


def test_validate_cloud_run_deploy_env_keeps_auth0_management_out_of_staging():
    management = {
        "AUTH0_MANAGEMENT_DOMAIN": "policyengine.us.auth0.com",
        "AUTH0_MANAGEMENT_CLIENT_ID": "management-client",
        "AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE": TEST_AUTH0_SECRET_RESOURCE,
    }
    staging = _script_env(**_staging_runtime_env(), **management)
    production = _script_env(**_required_runtime_env(), **management)

    staging_result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh", staging
    )
    production_result = _run_script(
        ".github/scripts/validate_cloud_run_deploy_env.sh", production
    )

    assert staging_result.returncode == 1
    assert "production-only" in staging_result.stderr
    assert production_result.returncode == 0, production_result.stderr


def test_validate_cloud_run_deploy_env_accepts_disabled_user_auth():
    env = _script_env(**_required_runtime_env())
    env["PUBLIC_API_AUTH_REQUIRED"] = "0"
    env.pop("PUBLIC_API_AUTH_ISSUER")
    env.pop("PUBLIC_API_AUTH_AUDIENCE")

    result = _run_script(".github/scripts/validate_cloud_run_deploy_env.sh", env)

    assert result.returncode == 0, result.stderr
