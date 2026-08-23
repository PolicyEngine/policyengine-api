import pytest

import policyengine_api.migration_flags as migration_flags
from policyengine_api.migration_flags import (
    get_migration_context,
    infer_route_group,
)
from policyengine_api.migration_registry import ROUTE_GROUP_CONFIG_BY_NAME


def test_stage6_route_implementation_values_are_typed():
    assert migration_flags.RouteImplementation.FLASK_FALLBACK.value == (
        "flask_fallback"
    )
    assert migration_flags.RouteImplementation.FASTAPI_NATIVE.value == "fastapi_native"


def test_stage6_route_settings_default_to_flask_fallback(monkeypatch):
    for name in (
        "ROUTE_IMPL_HEALTH",
        "ROUTE_IMPL_SPECIFICATION",
        "ROUTE_IMPL_METADATA",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = migration_flags.RouteImplementationSettings.from_environment()

    assert settings == migration_flags.RouteImplementationSettings(
        health=migration_flags.RouteImplementation.FLASK_FALLBACK,
        specification=migration_flags.RouteImplementation.FLASK_FALLBACK,
        metadata=migration_flags.RouteImplementation.FLASK_FALLBACK,
    )


def test_stage6_route_settings_are_independent(monkeypatch):
    monkeypatch.setenv("ROUTE_IMPL_HEALTH", "fastapi_native")
    monkeypatch.setenv("ROUTE_IMPL_SPECIFICATION", "flask_fallback")
    monkeypatch.setenv("ROUTE_IMPL_METADATA", "fastapi_native")

    settings = migration_flags.RouteImplementationSettings.from_environment()

    assert settings.health is migration_flags.RouteImplementation.FASTAPI_NATIVE
    assert settings.specification is migration_flags.RouteImplementation.FLASK_FALLBACK
    assert settings.metadata is migration_flags.RouteImplementation.FASTAPI_NATIVE


def test_stage6_route_settings_reject_invalid_values(monkeypatch):
    monkeypatch.setenv("ROUTE_IMPL_SPECIFICATION", "maybe")

    with pytest.raises(
        ValueError,
        match=(
            "ROUTE_IMPL_SPECIFICATION='maybe' is invalid; expected one of: "
            "fastapi_native, flask_fallback"
        ),
    ):
        migration_flags.RouteImplementationSettings.from_environment()


def test_stage6_route_groups_are_declared_in_migration_registry():
    assert {"health", "specification", "metadata"} <= set(ROUTE_GROUP_CONFIG_BY_NAME)


def test_default_migration_context_preserves_current_behavior(monkeypatch):
    for key in (
        "API_HOST_BACKEND",
        "ROUTE_IMPL_POLICY",
        "DB_WRITE_POLICY",
        "DB_READ_POLICY",
        "SIM_ENTRYPOINT",
    ):
        monkeypatch.delenv(key, raising=False)

    context = get_migration_context("policy")

    assert context.api_host_backend == "app_engine"
    assert context.route_impl == "flask_fallback"
    assert context.db_entity == "policy"
    assert context.db_write == "cloud_sql"
    assert context.db_read == "cloud_sql"
    assert context.sim_entrypoint == "old_gateway_direct"
    assert context.sim_compute is None


def test_explicit_valid_migration_context_values(monkeypatch):
    monkeypatch.setenv("API_HOST_BACKEND", "cloud_run")
    monkeypatch.setenv("ROUTE_IMPL_ECONOMY", "fastapi_native")
    monkeypatch.setenv("DB_WRITE_SIMULATION", "dual_write")
    monkeypatch.setenv("DB_READ_SIMULATION", "read_compare")
    monkeypatch.setenv("SIM_ENTRYPOINT", "cloud_run_simulation_entrypoint")
    monkeypatch.setenv("SIM_COMPUTE_ECONOMY", "v2_shadow")

    context = get_migration_context("economy")

    assert context.api_host_backend == "cloud_run"
    assert context.route_impl == "fastapi_native"
    assert context.db_entity == "simulation"
    assert context.db_write == "dual_write"
    assert context.db_read == "read_compare"
    assert context.sim_entrypoint == "cloud_run_simulation_entrypoint"
    assert context.sim_compute == "v2_shadow"


def test_invalid_migration_flag_raises(monkeypatch):
    monkeypatch.setenv("DB_READ_POLICY", "spreadsheets")

    with pytest.raises(ValueError, match="DB_READ_POLICY"):
        get_migration_context("policy")


@pytest.mark.parametrize(
    ("path", "expected_group"),
    [
        ("/", "home"),
        ("/health", "health"),
        ("/simulation-gateway-check", "health"),
        ("/readiness-check", "health"),
        ("/us/metadata", "metadata"),
        ("/us/policy/1", "policy"),
        ("/us/policies", "policy"),
        ("/us/household/1", "household"),
        ("/us/calculate", "household"),
        ("/us/economy/1/over/2", "economy"),
        ("/us/economy/1/over/2/budget-window", "economy"),
        ("/us/simulation/1", "simulation"),
        ("/simulations", "simulation"),
        ("/us/report/1", "report"),
    ],
)
def test_infer_route_group(path, expected_group):
    assert infer_route_group(path) == expected_group
