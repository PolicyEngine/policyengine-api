import pytest

from policyengine_api.migration_flags import (
    get_migration_context,
    infer_route_group,
)


def test_default_migration_context_preserves_current_behavior(monkeypatch):
    for key in (
        "API_HOST_BACKEND",
        "ROUTE_IMPL_POLICY",
        "DB_WRITE_POLICY",
        "DB_READ_POLICY",
        "SIM_FRONT_DOOR",
    ):
        monkeypatch.delenv(key, raising=False)

    context = get_migration_context("policy")

    assert context.api_host_backend == "app_engine"
    assert context.route_impl == "flask_fallback"
    assert context.db_entity == "policy"
    assert context.db_write == "cloud_sql"
    assert context.db_read == "cloud_sql"
    assert context.sim_front_door == "old_gateway_direct"
    assert context.sim_compute is None


def test_explicit_valid_migration_context_values(monkeypatch):
    monkeypatch.setenv("API_HOST_BACKEND", "cloud_run")
    monkeypatch.setenv("ROUTE_IMPL_ECONOMY", "fastapi_native")
    monkeypatch.setenv("DB_WRITE_SIMULATION", "dual_write")
    monkeypatch.setenv("DB_READ_SIMULATION", "read_compare")
    monkeypatch.setenv("SIM_FRONT_DOOR", "cloud_run_facade")
    monkeypatch.setenv("SIM_COMPUTE_ECONOMY", "v2_shadow")

    context = get_migration_context("economy")

    assert context.api_host_backend == "cloud_run"
    assert context.route_impl == "fastapi_native"
    assert context.db_entity == "simulation"
    assert context.db_write == "dual_write"
    assert context.db_read == "read_compare"
    assert context.sim_front_door == "cloud_run_facade"
    assert context.sim_compute == "v2_shadow"


def test_invalid_migration_flag_raises(monkeypatch):
    monkeypatch.setenv("DB_READ_POLICY", "spreadsheets")

    with pytest.raises(ValueError, match="DB_READ_POLICY"):
        get_migration_context("policy")


@pytest.mark.parametrize(
    ("path", "expected_group"),
    [
        ("/", "home"),
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
        ("/us/ai-prompts/simulation_analysis", "ai"),
    ],
)
def test_infer_route_group(path, expected_group):
    assert infer_route_group(path) == expected_group
