from unittest.mock import MagicMock

from flask import Flask


class FakeRedis:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, key):
        self.values.pop(key, None)


def _create_client(economy_bp):
    app = Flask(__name__)
    app.register_blueprint(economy_bp)
    return app.test_client()


def test_budget_window_in_flight_dedupe_uses_existing_batch_without_live_db(
    monkeypatch,
):
    monkeypatch.setenv("POLICYENGINE_DB_PASSWORD", "test")
    monkeypatch.setenv("FLASK_DEBUG", "1")

    from policyengine_api.libs.simulation_api_modal import (
        ModalBudgetWindowBatchExecution,
    )
    from policyengine_api.routes.economy_routes import economy_bp
    from policyengine_api.services import economy_service as economy_service_module
    from policyengine_api.services.budget_window_cache import BudgetWindowCache

    fake_cache = BudgetWindowCache(client=FakeRedis())
    simulation_api = MagicMock()
    reform_impacts_service = MagicMock()

    simulation_api.run_budget_window_batch.return_value = (
        ModalBudgetWindowBatchExecution(
            batch_job_id="fc-budget-window-parent",
            status="submitted",
        )
    )
    simulation_api.get_budget_window_batch_by_id.return_value = (
        ModalBudgetWindowBatchExecution(
            batch_job_id="fc-budget-window-parent",
            status="running",
            progress=50,
            completed_years=["2026"],
            running_years=["2027"],
            queued_years=["2028"],
        )
    )

    monkeypatch.setattr(economy_service_module, "budget_window_cache", fake_cache)
    monkeypatch.setattr(economy_service_module, "simulation_api", simulation_api)
    monkeypatch.setattr(
        economy_service_module,
        "reform_impacts_service",
        reform_impacts_service,
    )
    monkeypatch.setattr(
        economy_service_module.EconomyService,
        "_build_budget_window_batch_payload",
        lambda self, **kwargs: {
            "country_id": "us",
            "start_year": kwargs["start_year"],
            "window_size": kwargs["window_size"],
            "max_parallel": kwargs["max_parallel"],
        },
    )

    client = _create_client(economy_bp)
    path = "/us/economy/123/over/456/budget-window"
    params = {
        "region": "us",
        "dataset": "hf://policyengine/test.h5@1.0",
        "start_year": "2026",
        "window_size": "3",
    }

    first_response = client.get(path, query_string=params)
    first_payload = first_response.get_json()

    assert first_response.status_code == 200
    assert first_response.headers["X-PolicyEngine-Budget-Window-Cache"] == "miss"
    assert first_payload["status"] == "computing"
    assert first_payload["queued_years"] == ["2026", "2027", "2028"]

    second_response = client.get(path, query_string=params)
    second_payload = second_response.get_json()

    assert second_response.status_code == 200
    assert (
        second_response.headers["X-PolicyEngine-Budget-Window-Cache"] == "batch-id-hit"
    )
    assert second_payload["status"] == "computing"
    assert second_payload["progress"] == 50
    assert second_payload["completed_years"] == ["2026"]
    assert second_payload["computing_years"] == ["2027"]
    assert second_payload["queued_years"] == ["2028"]

    simulation_api.run_budget_window_batch.assert_called_once()
    simulation_api.get_budget_window_batch_by_id.assert_called_once_with(
        "fc-budget-window-parent"
    )
    reform_impacts_service.assert_not_called()
