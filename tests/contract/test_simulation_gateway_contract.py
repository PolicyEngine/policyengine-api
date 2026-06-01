from unittest.mock import MagicMock

import httpx
import pytest

import policyengine_api.libs.simulation_api_modal as simulation_api_modal
from policyengine_api.libs.simulation_api_modal import SimulationAPIModal
from tests.fixtures.libs.simulation_api_modal import (
    MOCK_BATCH_JOB_ID,
    MOCK_BATCH_POLL_RESPONSE_COMPLETE,
    MOCK_BATCH_SUBMIT_RESPONSE_SUCCESS,
    MOCK_HEALTH_RESPONSE,
    MOCK_MODAL_JOB_ID,
    MOCK_POLL_RESPONSE_COMPLETE,
    MOCK_RESOLVED_APP_NAME,
    MOCK_SIMULATION_PAYLOAD_WITH_TELEMETRY,
    MOCK_SUBMIT_RESPONSE_SUCCESS,
)


@pytest.fixture(autouse=True)
def disable_modal_logging(monkeypatch):
    monkeypatch.setattr(simulation_api_modal, "logger", MagicMock())


def _client_for(responses: dict[tuple[str, str], httpx.Response]) -> SimulationAPIModal:
    transport = httpx.MockTransport(
        lambda request: responses[(request.method, request.url.path)]
    )
    client = SimulationAPIModal()
    client.client = httpx.Client(
        base_url=client.base_url,
        transport=transport,
    )
    return client


def _response(status_code: int, json_data: dict) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=json_data)


def _clear_gateway_auth_env(monkeypatch):
    for key in (
        "GATEWAY_AUTH_ISSUER",
        "GATEWAY_AUTH_AUDIENCE",
        "GATEWAY_AUTH_CLIENT_ID",
        "GATEWAY_AUTH_CLIENT_SECRET",
        "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE",
        "GATEWAY_AUTH_REQUIRED",
    ):
        monkeypatch.delenv(key, raising=False)


def test_gateway_comparison_submit_and_poll_contract(monkeypatch):
    _clear_gateway_auth_env(monkeypatch)
    monkeypatch.setenv("SIMULATION_API_URL", "https://simulation.test")
    client = _client_for(
        {
            ("POST", "/simulate/economy/comparison"): _response(
                status_code=202,
                json_data=MOCK_SUBMIT_RESPONSE_SUCCESS,
            ),
            ("GET", f"/jobs/{MOCK_MODAL_JOB_ID}"): _response(
                status_code=200,
                json_data=MOCK_POLL_RESPONSE_COMPLETE,
            ),
        }
    )

    execution = client.run(
        {
            **MOCK_SIMULATION_PAYLOAD_WITH_TELEMETRY,
            "model_version": "1.702.0",
            "data_version": "ignored-by-gateway",
        }
    )
    completed = client.get_execution_by_id(execution.job_id)

    assert execution.job_id == MOCK_MODAL_JOB_ID
    assert execution.status == "submitted"
    assert completed.status == "complete"
    assert completed.result == MOCK_POLL_RESPONSE_COMPLETE["result"]
    assert completed.resolved_app_name == MOCK_RESOLVED_APP_NAME


def test_gateway_budget_window_submit_and_poll_contract(monkeypatch):
    _clear_gateway_auth_env(monkeypatch)
    monkeypatch.setenv("SIMULATION_API_URL", "https://simulation.test")
    client = _client_for(
        {
            (
                "POST",
                "/simulate/economy/budget-window",
            ): _response(
                status_code=202,
                json_data=MOCK_BATCH_SUBMIT_RESPONSE_SUCCESS,
            ),
            (
                "GET",
                f"/budget-window-jobs/{MOCK_BATCH_JOB_ID}",
            ): _response(
                status_code=200,
                json_data=MOCK_BATCH_POLL_RESPONSE_COMPLETE,
            ),
        }
    )

    execution = client.run_budget_window_batch(
        {
            **MOCK_SIMULATION_PAYLOAD_WITH_TELEMETRY,
            "model_version": "1.702.0",
            "data_version": "ignored-by-gateway",
        }
    )
    completed = client.get_budget_window_batch_by_id(execution.batch_job_id)

    assert execution.batch_job_id == MOCK_BATCH_JOB_ID
    assert execution.status == "submitted"
    assert completed.status == "complete"
    assert completed.result == MOCK_BATCH_POLL_RESPONSE_COMPLETE["result"]


def test_gateway_versions_and_health_contract(monkeypatch):
    _clear_gateway_auth_env(monkeypatch)
    monkeypatch.setenv("SIMULATION_API_URL", "https://simulation.test")
    client = _client_for(
        {
            ("GET", "/versions/us"): _response(
                status_code=200,
                json_data={"latest": "1.702.0", "1.702.0": MOCK_RESOLVED_APP_NAME},
            ),
            ("GET", "/health"): _response(
                status_code=200,
                json_data=MOCK_HEALTH_RESPONSE,
            ),
        }
    )

    app_name, version = client.resolve_app_name("us")

    assert app_name == MOCK_RESOLVED_APP_NAME
    assert version == "1.702.0"
    assert client.health_check() is True
