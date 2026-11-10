"""Submit household calculations to the simulation service and read its answers."""

from __future__ import annotations

import json
from uuid import UUID

import httpx
import pytest

from policyengine_api.libs.gateway_auth import GatewayAuthError
from policyengine_api.libs.simulation_household_calculations import (
    HOUSEHOLD_CALCULATIONS_PATH,
    SimulationAnswer,
    SimulationHouseholdCalculationClient,
)
from policyengine_api.services.v2.household_calculations.types import (
    HouseholdCalculationAccepted,
    SimulationServiceAnswerUnreadableError,
    SimulationServiceInvalidRequestError,
    SimulationServiceUnavailableError,
)
from tests.fixtures.household_calculation_documents import JOB_ID
from tests.unit.v2.household_calculation_support import (
    HOUSEHOLD_ID,
    POLICY_ID,
    calculation_input,
)

SIMULATION_URL = "https://simulation.example.test"
ENVIRONMENT_VARIABLES = (
    "GATEWAY_AUTH_ISSUER",
    "GATEWAY_AUTH_AUDIENCE",
    "GATEWAY_AUTH_CLIENT_ID",
    "GATEWAY_AUTH_CLIENT_SECRET",
    "GATEWAY_AUTH_CLIENT_SECRET_RESOURCE",
    "GATEWAY_AUTH_REQUIRED",
    "SIM_ENTRYPOINT",
    "OLD_SIMULATION_GATEWAY_URL",
    "SIMULATION_ENTRYPOINT_URL",
)
ACCEPTED = {"job_id": str(JOB_ID), "status": "pending"}


@pytest.fixture(autouse=True)
def configured_simulation_service(monkeypatch):
    """Name the Cloud Run simulation service; set no gateway credentials."""
    for name in ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", f"{SIMULATION_URL}/")
    # The household routes exist only on the Cloud Run simulation service,
    # whatever the economy routes select.
    monkeypatch.setenv("SIM_ENTRYPOINT", "old_gateway_direct")
    monkeypatch.setenv("OLD_SIMULATION_GATEWAY_URL", "https://old.example.test")


class RecordingService:
    """The simulation service, answering every request with one scripted answer."""

    def __init__(self, status_code: int = 202, body: object = ACCEPTED) -> None:
        self.status_code = status_code
        self.body = body
        self.requests: list[httpx.Request] = []

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.body, bytes):
            return httpx.Response(self.status_code, content=self.body)
        return httpx.Response(self.status_code, json=self.body)

    def client(self) -> SimulationHouseholdCalculationClient:
        return SimulationHouseholdCalculationClient.from_environment(
            transport=httpx.MockTransport(self.answer)
        )

    def sent_body(self) -> dict[str, object]:
        (request,) = self.requests
        return json.loads(request.content)


def test_a_submission_is_posted_and_its_new_job_returned() -> None:
    service = RecordingService()

    accepted = service.client().submit(calculation_input())

    assert accepted == HouseholdCalculationAccepted(
        calculation_id=JOB_ID, status="pending"
    )
    (request,) = service.requests
    assert request.method == "POST"
    assert str(request.url) == f"{SIMULATION_URL}{HOUSEHOLD_CALCULATIONS_PATH}"
    assert service.sent_body() == {
        "country": "us",
        "household_id": str(HOUSEHOLD_ID),
        "policy_id": str(POLICY_ID),
        "add_missing_variables": False,
    }


def test_current_law_sends_a_null_policy() -> None:
    service = RecordingService()

    service.client().submit(calculation_input(policy_id=None))

    assert service.sent_body()["policy_id"] is None


def test_axes_and_spm_settings_are_sent_only_as_the_caller_gave_them() -> None:
    service = RecordingService()
    axis = {"name": "employment_income", "count": 5, "min": 0, "max": 50_000}

    service.client().submit(
        calculation_input(
            add_missing_variables=True,
            axes=[[{**axis, "period": "2026"}], [axis]],
            spm={"scenario": "ce_trend", "geography_kind": "national"},
        )
    )

    body = service.sent_body()
    assert body["add_missing_variables"] is True
    assert body["axes"] == [[{**axis, "period": "2026"}], [axis]]
    assert body["spm"] == {"scenario": "ce_trend", "geography_kind": "national"}


def test_an_answer_with_fields_the_public_api_does_not_read_is_accepted() -> None:
    service = RecordingService(body={**ACCEPTED, "created_at": "2026-11-10T12:00Z"})

    accepted = service.client().submit(calculation_input())

    assert accepted.calculation_id == JOB_ID


def test_caller_data_the_service_refuses_is_reported_with_its_reason() -> None:
    service = RecordingService(422, {"detail": "the policy value is an object"})

    with pytest.raises(SimulationServiceInvalidRequestError) as refused:
        service.client().submit(calculation_input())

    assert str(refused.value) == (
        "The simulation service cannot calculate this household: "
        "the policy value is an object"
    )


def test_request_fields_the_service_refuses_are_reported_one_by_one() -> None:
    service = RecordingService(
        422,
        {
            "detail": [
                {"loc": ["body", "axes", 0, 0, "count"], "msg": "too large"},
                {"loc": ["body", "spm"], "msg": "must be an object", "type": "x"},
            ]
        },
    )

    with pytest.raises(SimulationServiceInvalidRequestError) as refused:
        service.client().submit(calculation_input())

    assert str(refused.value) == (
        "The simulation service cannot calculate this household: "
        "axes.0.0.count: too large; spm: must be an object"
    )


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"detail": {"nested": "object"}}, id="detail-object"),
        pytest.param({"detail": [{"msg": "no location"}]}, id="field-without-loc"),
        pytest.param({"message": "no detail"}, id="no-detail"),
        pytest.param(b"not json", id="not-json"),
    ],
)
def test_a_refusal_of_another_shape_is_unavailable(body) -> None:
    service = RecordingService(422, body)

    with pytest.raises(SimulationServiceUnavailableError, match="could not be read"):
        service.client().submit(calculation_input())


def test_a_reference_the_service_cannot_find_is_unavailable_with_its_reason() -> None:
    service = RecordingService(
        400,
        {"code": "unknown_household", "detail": f"Household {HOUSEHOLD_ID} not found"},
    )

    with pytest.raises(SimulationServiceUnavailableError) as refused:
        service.client().submit(calculation_input())

    assert str(refused.value) == (
        "The simulation service refused the calculation (unknown_household): "
        f"Household {HOUSEHOLD_ID} not found"
    )


def test_a_modal_call_the_service_could_not_start_names_the_failed_job() -> None:
    service = RecordingService(
        503,
        {
            "code": "modal_call_refused",
            "detail": "Modal refused the household function's call",
            "household_job_id": str(JOB_ID),
        },
    )

    with pytest.raises(SimulationServiceUnavailableError) as refused:
        service.client().submit(calculation_input())

    assert str(refused.value) == (
        "The simulation service is unavailable (modal_call_refused): Modal "
        f"refused the household function's call; it failed household job {JOB_ID}"
    )


def test_a_dependency_the_service_cannot_read_names_its_code() -> None:
    service = RecordingService(
        503, {"code": "database_unavailable", "detail": "The database is down"}
    )

    with pytest.raises(SimulationServiceUnavailableError) as refused:
        service.client().submit(calculation_input())

    assert str(refused.value) == (
        "The simulation service is unavailable (database_unavailable): "
        "The database is down"
    )


@pytest.mark.parametrize("status_code", [400, 401, 404, 500, 502, 503])
def test_any_other_answer_is_unavailable(status_code) -> None:
    service = RecordingService(status_code, b"")

    with pytest.raises(SimulationServiceUnavailableError, match=str(status_code)):
        service.client().submit(calculation_input())


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"not json", id="not-json"),
        pytest.param({"status": "pending"}, id="no-job-id"),
        pytest.param({"job_id": "not-a-uuid", "status": "pending"}, id="bad-id"),
        pytest.param({"job_id": str(JOB_ID), "status": "queued"}, id="bad-status"),
    ],
)
def test_an_accepted_answer_that_cannot_be_read_is_not_unavailable(body) -> None:
    # The service has created the job and started its call, so the caller is
    # told the answer was unreadable rather than to try again.
    service = RecordingService(202, body)

    with pytest.raises(SimulationServiceAnswerUnreadableError) as unreadable:
        service.client().submit(calculation_input())

    assert not isinstance(unreadable.value, SimulationServiceUnavailableError)
    assert str(unreadable.value) == (
        "The simulation service accepted the calculation, but its answer "
        "could not be read."
    )


def test_an_unreachable_service_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        msg = "connection refused"
        raise httpx.ConnectError(msg, request=request)

    client = SimulationHouseholdCalculationClient.from_environment(
        transport=httpx.MockTransport(refuse)
    )

    with pytest.raises(SimulationServiceUnavailableError, match="could not be reached"):
        client.submit(calculation_input())


def test_a_gateway_token_that_cannot_be_fetched_is_unavailable() -> None:
    def refuse_token(http_client, body) -> SimulationAnswer:
        msg = "Auth0 refused the client credentials"
        raise GatewayAuthError(msg)

    client = SimulationHouseholdCalculationClient(
        httpx.Client(base_url=SIMULATION_URL), send=refuse_token
    )

    with pytest.raises(SimulationServiceUnavailableError, match="could not be reached"):
        client.submit(calculation_input())


def test_the_request_is_sent_through_the_one_replaceable_send_function() -> None:
    sent: list[dict[str, object]] = []

    def send(http_client: httpx.Client, body: dict[str, object]) -> SimulationAnswer:
        assert str(http_client.base_url).rstrip("/") == SIMULATION_URL
        sent.append(body)
        return SimulationAnswer(status_code=202, content=json.dumps(ACCEPTED).encode())

    client = SimulationHouseholdCalculationClient(
        httpx.Client(base_url=SIMULATION_URL), send=send
    )

    accepted = client.submit(calculation_input(policy_id=None))

    assert accepted.calculation_id == UUID(ACCEPTED["job_id"])
    assert sent == [
        {
            "country": "us",
            "household_id": str(HOUSEHOLD_ID),
            "policy_id": None,
            "add_missing_variables": False,
        }
    ]


def test_a_missing_service_url_is_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("SIMULATION_ENTRYPOINT_URL")

    with pytest.raises(SimulationServiceUnavailableError, match="not configured"):
        SimulationHouseholdCalculationClient.from_environment()


def test_partly_configured_gateway_credentials_are_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("GATEWAY_AUTH_ISSUER", "https://tenant.example.test/")

    with pytest.raises(SimulationServiceUnavailableError, match="not configured"):
        SimulationHouseholdCalculationClient.from_environment()


def test_required_but_missing_gateway_credentials_are_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("GATEWAY_AUTH_REQUIRED", "1")

    with pytest.raises(SimulationServiceUnavailableError, match="not configured"):
        SimulationHouseholdCalculationClient.from_environment()
