"""The simulation service's household calculation routes, through its client.

These tests need a simulation client with the household calculation routes.
"""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from policyengine_api.libs.gateway_auth import GatewayAuthError
from policyengine_api.services.v2.household_calculations.simulation_client import (
    SimulationHouseholdClient,
)
from policyengine_api.services.v2.household_calculations.types import (
    SimulationServiceInvalidRequestError,
    SimulationServiceRefusedError,
    SimulationServiceUnavailableError,
)
from tests.unit.v2.household_calculation_support import (
    CALCULATION_ID,
    CATALOG_VERSION_ID,
    HOUSEHOLD_ID,
    POLICYENGINE_VERSION,
    SITUATION,
    simulation_calculation,
    succeeded_calculation,
)

BASE_URL = "https://simulation.example"
SUBMISSION = {
    "country": "us",
    "catalog_version_id": str(CATALOG_VERSION_ID),
    "policyengine_version": POLICYENGINE_VERSION,
    "year": 2026,
    "household_id": str(HOUSEHOLD_ID),
    "household": SITUATION,
    "spm": {"scenario": "ce_trend"},
    "policy": {"policy_id": None, "parameters": {}},
    "options": {"axes": None, "add_missing_variables": False},
    "force": False,
    "trigger": "initial",
}


def client_answering(
    status_code: int, payload: object, requests: list
) -> SimulationHouseholdClient:
    """Return a client whose requests get one fixed answer."""

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code, json=payload)

    return SimulationHouseholdClient(
        BASE_URL, httpx_args={"transport": httpx.MockTransport(answer)}
    )


def test_a_submission_is_posted_and_its_calculation_returned() -> None:
    requests: list[httpx.Request] = []
    client = client_answering(202, simulation_calculation(), requests)

    calculation = client.submit(SUBMISSION)

    assert calculation == simulation_calculation()
    (request,) = requests
    assert request.method == "POST"
    assert str(request.url) == f"{BASE_URL}/v2/household-calculations"
    assert json.loads(request.content) == SUBMISSION


def test_a_calculation_is_read_by_id() -> None:
    requests: list[httpx.Request] = []
    client = client_answering(200, succeeded_calculation(), requests)

    assert client.read(CALCULATION_ID) == succeeded_calculation()
    assert str(requests[0].url) == (
        f"{BASE_URL}/v2/household-calculations/{CALCULATION_ID}"
    )


def test_an_unknown_calculation_reads_as_none() -> None:
    client = client_answering(404, {"detail": "No such household calculation."}, [])

    assert client.read(uuid4()) is None


def test_a_refusal_carries_the_services_reason() -> None:
    client = client_answering(
        400, {"detail": "PolicyEngine.py 9.9.9 has no deployed v2 worker"}, []
    )

    with pytest.raises(SimulationServiceRefusedError, match=r"9\.9\.9"):
        client.submit(SUBMISSION)


@pytest.mark.parametrize("status_code", [500, 503])
def test_a_service_that_cannot_answer_is_unavailable(status_code: int) -> None:
    client = client_answering(status_code, {"detail": "unavailable"}, [])

    with pytest.raises(SimulationServiceUnavailableError):
        client.submit(SUBMISSION)
    with pytest.raises(SimulationServiceUnavailableError):
        client.read(CALCULATION_ID)


def test_an_unreachable_service_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        message = "refused"
        raise httpx.ConnectError(message, request=request)

    client = SimulationHouseholdClient(
        BASE_URL, httpx_args={"transport": httpx.MockTransport(refuse)}
    )

    with pytest.raises(SimulationServiceUnavailableError):
        client.read(CALCULATION_ID)


GATEWAY_AUTH_VARIABLES = (
    "GATEWAY_AUTH_ISSUER",
    "GATEWAY_AUTH_AUDIENCE",
    "GATEWAY_AUTH_CLIENT_ID",
    "GATEWAY_AUTH_CLIENT_SECRET",
    "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE",
    "GATEWAY_AUTH_REQUIRED",
)


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"SIMULATION_ENTRYPOINT_URL": "not a url"},
        {
            "SIMULATION_ENTRYPOINT_URL": BASE_URL,
            "GATEWAY_AUTH_ISSUER": "https://issuer.example/",
        },
        {"SIMULATION_ENTRYPOINT_URL": BASE_URL, "GATEWAY_AUTH_REQUIRED": "true"},
    ],
    ids=["no-url", "invalid-url", "partial-auth", "auth-required"],
)
def test_a_misconfigured_service_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, environment: dict[str, str]
) -> None:
    for name in ("SIMULATION_ENTRYPOINT_URL", *GATEWAY_AUTH_VARIABLES):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(SimulationServiceUnavailableError, match="not configured"):
        SimulationHouseholdClient.from_environment()


def test_the_configured_service_is_called_without_auth_when_none_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in GATEWAY_AUTH_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", f"{BASE_URL}/")

    client = SimulationHouseholdClient.from_environment()

    assert client.base_url == BASE_URL


def test_a_household_the_service_finds_invalid_is_reported_with_its_reasons() -> None:
    client = client_answering(
        422,
        {
            "detail": [
                {
                    "loc": ["body", "household", "households", "h", "members"],
                    "msg": "List should have at least 1 item after validation",
                    "type": "too_short",
                }
            ]
        },
        [],
    )

    with pytest.raises(
        SimulationServiceInvalidRequestError,
        match=r"household\.households\.h\.members: List should have at least 1 item",
    ):
        client.submit(SUBMISSION)


@pytest.mark.parametrize("status_code", [400, 503, 202, 200])
def test_an_answer_that_is_not_json_is_unavailable(status_code: int) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            content=b"<html><body>Service Unavailable</body></html>",
            headers={"Content-Type": "text/html"},
        )

    client = SimulationHouseholdClient(
        BASE_URL, httpx_args={"transport": httpx.MockTransport(answer)}
    )

    with pytest.raises(SimulationServiceUnavailableError):
        client.submit(SUBMISSION)
    with pytest.raises(SimulationServiceUnavailableError):
        client.read(CALCULATION_ID)


def test_an_answer_of_the_wrong_shape_is_unavailable() -> None:
    client = client_answering(202, {"calculation_id": "not a calculation"}, [])

    with pytest.raises(SimulationServiceUnavailableError):
        client.submit(SUBMISSION)


def test_a_gateway_token_that_cannot_be_fetched_is_unavailable() -> None:
    class FailingTokenAuth(httpx.Auth):
        def auth_flow(self, request: httpx.Request):  # httpx's generator protocol
            message = "The gateway token request failed"
            raise GatewayAuthError(message)
            yield request

    client = SimulationHouseholdClient(
        BASE_URL,
        httpx_args={
            "auth": FailingTokenAuth(),
            "transport": httpx.MockTransport(
                lambda request: httpx.Response(202, json=simulation_calculation())
            ),
        },
    )

    with pytest.raises(SimulationServiceUnavailableError):
        client.submit(SUBMISSION)
    with pytest.raises(SimulationServiceUnavailableError):
        client.read(CALCULATION_ID)


def test_the_household_keeps_its_key_order_both_ways() -> None:
    requests: list[httpx.Request] = []
    answer = succeeded_calculation()
    client = client_answering(200, answer, requests)
    submit_client = client_answering(202, answer, requests)

    submitted = submit_client.submit(SUBMISSION)
    read = client.read(CALCULATION_ID)

    sent_household = json.loads(requests[0].content)["household"]
    assert list(sent_household) == list(SITUATION)
    assert list(sent_household["households"]["household-1"]) == list(
        SITUATION["households"]["household-1"]
    )
    for calculation in (submitted, read):
        assert calculation is not None
        returned_household = calculation["result"]["household"]
        assert list(returned_household) == list(answer["result"]["household"])
        assert list(returned_household["households"]["household-1"]) == list(
            answer["result"]["household"]["households"]["household-1"]
        )
