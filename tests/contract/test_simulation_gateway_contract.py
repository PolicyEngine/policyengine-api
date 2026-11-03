import json
from unittest.mock import MagicMock

import httpx
import pytest

from policyengine_api.libs import simulation_entrypoint
from policyengine_api.libs.simulation_entrypoint import SimulationAPIModal
from policyengine_api.services.economy_service import (
    EconomicImpactSetupOptions,
    EconomyService,
)
from tests.fixtures.libs.simulation_entrypoint import (
    MOCK_BATCH_JOB_ID,
    MOCK_BATCH_POLL_RESPONSE_COMPLETE,
    MOCK_BATCH_SUBMIT_RESPONSE_SUCCESS,
    MOCK_HEALTH_RESPONSE,
    MOCK_LOCAL_AREA_BREAKDOWN_RESULT,
    MOCK_LOCAL_AREA_BREAKDOWN_RESULT_WITH_WITHHELD_CODES,
    MOCK_MODAL_JOB_ID,
    MOCK_POLL_RESPONSE_COMPLETE,
    MOCK_RESOLVED_APP_NAME,
    MOCK_SIMULATION_PAYLOAD_WITH_TELEMETRY,
    MOCK_SUBMIT_RESPONSE_SUCCESS,
    MOCK_WORKER_VERSIONS,
)


@pytest.fixture(autouse=True)
def disable_modal_logging(monkeypatch):
    monkeypatch.setattr(simulation_entrypoint, "logger", MagicMock())


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
    monkeypatch.setenv("OLD_SIMULATION_GATEWAY_URL", "https://simulation.test")
    client = _client_for(
        {
            ("GET", "/versions"): _response(
                status_code=200,
                json_data=MOCK_WORKER_VERSIONS,
            ),
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
    monkeypatch.setenv("OLD_SIMULATION_GATEWAY_URL", "https://simulation.test")
    client = _client_for(
        {
            ("GET", "/versions"): _response(
                status_code=200,
                json_data=MOCK_WORKER_VERSIONS,
            ),
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
        }
    )
    completed = client.get_budget_window_batch_by_id(execution.batch_job_id)

    assert execution.batch_job_id == MOCK_BATCH_JOB_ID
    assert execution.status == "submitted"
    assert completed.status == "complete"
    assert completed.result == MOCK_BATCH_POLL_RESPONSE_COMPLETE["result"]


def test_gateway_versions_and_health_contract(monkeypatch):
    _clear_gateway_auth_env(monkeypatch)
    monkeypatch.setenv("OLD_SIMULATION_GATEWAY_URL", "https://simulation.test")
    client = _client_for(
        {
            ("GET", "/versions/us"): _response(
                status_code=200,
                json_data={"latest": "1.702.0", "1.702.0": MOCK_RESOLVED_APP_NAME},
            ),
            ("GET", "/versions/policyengine"): _response(
                status_code=200,
                json_data={"latest": "4.18.3", "4.18.3": MOCK_RESOLVED_APP_NAME},
            ),
            ("GET", "/health"): _response(
                status_code=200,
                json_data=MOCK_HEALTH_RESPONSE,
            ),
        }
    )

    app_name, version = client.resolve_app_name("us")
    bundle_app_name, bundle_version = client.resolve_app_name(
        "us",
        "1.729.0",
        policyengine_version="4.18.3",
    )

    assert app_name == MOCK_RESOLVED_APP_NAME
    assert version == "1.702.0"
    assert bundle_app_name == MOCK_RESOLVED_APP_NAME
    assert bundle_version == "1.729.0"
    assert client.health_check() is True


def _uk_submission(options: dict) -> dict:
    """Return the annual UK payload the economy service builds for these options."""
    setup_options = EconomicImpactSetupOptions(
        submission_claim_id="00000000-0000-4000-8000-000000000002",
        country_id="uk",
        reform_policy_id=2,
        baseline_policy_id=1,
        region="uk",
        dataset="default",
        time_period="2026",
        options=options,
        api_version="1.0",
        target="general",
        model_version="2.132.6",
        policyengine_version="6.10.0",
    )
    return (
        EconomyService()
        ._setup_sim_options(
            setup_options,
            reform_policy={"gov.hmrc.income_tax.allowances.personal_allowance": {}},
            baseline_policy={},
            time_period="2026",
        )
        .model_dump(mode="json")
    )


@pytest.mark.parametrize(
    ("options", "expected_breakdown", "result"),
    [
        (
            {"breakdown": "local_areas"},
            "local_areas",
            MOCK_LOCAL_AREA_BREAKDOWN_RESULT,
        ),
        (
            {"breakdown": "local_areas"},
            "local_areas",
            MOCK_LOCAL_AREA_BREAKDOWN_RESULT_WITH_WITHHELD_CODES,
        ),
        ({}, None, MOCK_POLL_RESPONSE_COMPLETE["result"]),
    ],
    ids=["local-area-breakdown", "local-area-breakdown-withheld-codes", "national"],
)
def test_gateway_uk_comparison_sends_breakdown_only_when_requested(
    monkeypatch, options, expected_breakdown, result
):
    _clear_gateway_auth_env(monkeypatch)
    monkeypatch.setenv("OLD_SIMULATION_GATEWAY_URL", "https://simulation.test")
    submitted_bodies = []

    def respond(request: httpx.Request) -> httpx.Response:
        if (request.method, request.url.path) == (
            "POST",
            "/simulate/economy/comparison",
        ):
            submitted_bodies.append(json.loads(request.content))
            return _response(202, MOCK_SUBMIT_RESPONSE_SUCCESS)
        assert (request.method, request.url.path) == (
            "GET",
            f"/jobs/{MOCK_MODAL_JOB_ID}",
        )
        return _response(200, {**MOCK_POLL_RESPONSE_COMPLETE, "result": result})

    client = SimulationAPIModal()
    client.client = httpx.Client(
        base_url=client.base_url, transport=httpx.MockTransport(respond)
    )

    execution = client.run(_uk_submission(options))
    completed = client.get_execution_by_id(execution.job_id)

    assert [body.get("breakdown") for body in submitted_bodies] == [expected_breakdown]
    assert ("breakdown" in submitted_bodies[0]) is (expected_breakdown is not None)
    assert submitted_bodies[0]["region"] == "uk"
    assert submitted_bodies[0]["include_cliffs"] is False
    assert completed.result == result
