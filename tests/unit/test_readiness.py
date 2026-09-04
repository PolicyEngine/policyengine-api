import pytest
from unittest.mock import patch

from policyengine_api import readiness


@pytest.fixture(autouse=True)
def _restore_ready():
    # readiness state is module-global; leave it ready for other tests.
    yield
    readiness.mark_ready()


def test_defaults_to_ready():
    assert readiness.is_ready() is True


def test_mark_not_ready_then_ready():
    readiness.mark_not_ready()
    assert readiness.is_ready() is False
    readiness.mark_ready()
    assert readiness.is_ready() is True


def test_default_cloud_sql_policy_mode_does_not_require_v2_settings(
    monkeypatch,
):
    monkeypatch.delenv("DB_WRITE_POLICY", raising=False)
    monkeypatch.delenv("DB_READ_POLICY", raising=False)
    monkeypatch.delenv("ROUTE_IMPL_POLICY", raising=False)
    monkeypatch.delenv("V2_RUNTIME_DATABASE_URL", raising=False)
    monkeypatch.delenv("V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE", raising=False)

    readiness.mark_ready()

    assert readiness.is_ready() is True


def test_dual_write_or_native_policy_routes_require_v2_runtime_settings(
    monkeypatch,
):
    monkeypatch.setenv("DB_WRITE_POLICY", "dual_write")
    monkeypatch.delenv("V2_RUNTIME_DATABASE_URL", raising=False)
    monkeypatch.delenv("V2_RUNTIME_DATABASE_URL_SECRET_RESOURCE", raising=False)
    readiness.mark_ready()

    assert readiness.is_ready() is False


def test_selected_v2_policy_modes_validate_runtime_settings(monkeypatch):
    monkeypatch.setenv("DB_WRITE_POLICY", "dual_write")
    monkeypatch.setenv("DB_READ_POLICY", "cloud_sql")
    monkeypatch.setenv("ROUTE_IMPL_POLICY", "flask_fallback")
    readiness.mark_ready()

    with patch(
        "policyengine_api.data.v2.settings.load_v2_runtime_database_settings",
        return_value=object(),
    ) as load_settings:
        assert readiness.is_ready() is True

    load_settings.assert_called_once_with()

    monkeypatch.setenv("DB_WRITE_POLICY", "cloud_sql")
    monkeypatch.setenv("ROUTE_IMPL_POLICY", "fastapi_native")

    assert readiness.is_ready() is False
