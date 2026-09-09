from unittest.mock import patch

import pytest

from policyengine_api import readiness


@pytest.fixture(autouse=True)
def _restore_ready():
    # readiness state is module-global; leave it ready for other tests.
    yield
    readiness.mark_ready()


def test_defaults_to_ready_when_v2_settings_are_valid():
    with patch(
        "policyengine_api.data.v2.settings.load_v2_runtime_database_settings",
        return_value=object(),
    ) as load_settings:
        assert readiness.is_ready() is True

    load_settings.assert_called_once_with()


def test_mark_not_ready_then_ready():
    with patch(
        "policyengine_api.data.v2.settings.load_v2_runtime_database_settings",
        return_value=object(),
    ) as load_settings:
        readiness.mark_not_ready()
        assert readiness.is_ready() is False
        load_settings.assert_not_called()

        readiness.mark_ready()
        assert readiness.is_ready() is True

    load_settings.assert_called_once_with()


def test_registered_native_household_routes_require_v2_settings_in_cloud_sql_mode(
    monkeypatch,
):
    monkeypatch.delenv("DB_WRITE_POLICY", raising=False)
    monkeypatch.delenv("DB_READ_POLICY", raising=False)
    monkeypatch.delenv("ROUTE_IMPL_POLICY", raising=False)
    monkeypatch.delenv("DB_WRITE_HOUSEHOLD", raising=False)
    monkeypatch.delenv("DB_READ_HOUSEHOLD", raising=False)
    monkeypatch.delenv("ROUTE_IMPL_HOUSEHOLD", raising=False)
    monkeypatch.delenv("V2_RUNTIME_DATABASE_URL", raising=False)
    monkeypatch.delenv("V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE", raising=False)

    readiness.mark_ready()

    assert readiness.is_ready() is False


def test_dual_write_policy_mode_requires_v2_runtime_settings(
    monkeypatch,
):
    monkeypatch.setenv("DB_WRITE_POLICY", "dual_write")
    monkeypatch.delenv("V2_RUNTIME_DATABASE_URL", raising=False)
    monkeypatch.delenv("V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE", raising=False)
    readiness.mark_ready()

    assert readiness.is_ready() is False


def test_cloud_sql_modes_validate_v2_runtime_settings(monkeypatch):
    monkeypatch.setenv("DB_WRITE_POLICY", "cloud_sql")
    monkeypatch.setenv("DB_READ_POLICY", "cloud_sql")
    monkeypatch.setenv("ROUTE_IMPL_POLICY", "flask_fallback")
    monkeypatch.setenv("DB_WRITE_HOUSEHOLD", "cloud_sql")
    monkeypatch.setenv("DB_READ_HOUSEHOLD", "cloud_sql")
    monkeypatch.setenv("ROUTE_IMPL_HOUSEHOLD", "flask_fallback")
    readiness.mark_ready()

    with patch(
        "policyengine_api.data.v2.settings.load_v2_runtime_database_settings",
        return_value=object(),
    ) as load_settings:
        assert readiness.is_ready() is True

    load_settings.assert_called_once_with()


def test_dual_write_households_require_v2_settings(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DB_WRITE_POLICY", "cloud_sql")
    monkeypatch.setenv("DB_READ_POLICY", "cloud_sql")
    monkeypatch.setenv("ROUTE_IMPL_POLICY", "flask_fallback")
    monkeypatch.setenv("DB_READ_HOUSEHOLD", "cloud_sql")
    monkeypatch.setenv("ROUTE_IMPL_HOUSEHOLD", "flask_fallback")
    monkeypatch.delenv("V2_RUNTIME_DATABASE_URL", raising=False)
    monkeypatch.delenv("V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE", raising=False)

    monkeypatch.setenv("DB_WRITE_HOUSEHOLD", "dual_write")
    assert readiness.is_ready() is False

    with patch(
        "policyengine_api.data.v2.settings.load_v2_runtime_database_settings",
        return_value=object(),
    ) as load_settings:
        assert readiness.is_ready() is True
    load_settings.assert_called_once_with()
