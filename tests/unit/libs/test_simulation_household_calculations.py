"""Submit household calculations to the simulation service and read its answers."""

from __future__ import annotations

import json
from uuid import UUID

import httpx
import pytest

from policyengine_api.fastapi_routes.v2.household_calculations.routes import (
    HOUSEHOLD_CALCULATION_ERROR_MAPPINGS,
)
from policyengine_api.libs.gateway_auth import GatewayAuthError
from policyengine_api.libs.simulation_household_calculations import (
    HOUSEHOLD_CALCULATIONS_PATH,
    SimulationAnswer,
    SimulationHouseholdCalculationClient,
)
from policyengine_api.request_context import _asgi_observability_id
from policyengine_api.services.v2.household_calculations.types import (
    HouseholdCalculationAccepted,
    SimulationServiceAnswerUnreadableError,
    SimulationServiceInternalError,
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


def lost_answer_message(what_happened: str) -> str:
    """Return the 502 message for an answer lost after the request may have arrived.

    No route finds a household job without its ID, so the caller is asked to
    submit again and told that this may create a second job.
    """
    return (
        "The simulation service may have received the request, but its answer "
        f"was lost ({what_happened}). Submit the household calculation again; "
        "if the first request went through, this creates a second job."
    )


def created_but_failed_message(status_and_code: str) -> str:
    """Return the 502 message for an answer sent after the job may exist.

    It names the service's status, and its code when that is a fixed
    identifier, never the service's text.
    """
    return (
        "The simulation service may have created the household job, but it "
        f"failed ({status_and_code}). Submit the household calculation again; "
        "if the first request went through, this creates a second job."
    )


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


def _route_status(error: Exception) -> int:
    """Return the status the household calculation route answers ``error`` with."""
    return next(
        mapping.status_code
        for mapping in HOUSEHOLD_CALCULATION_ERROR_MAPPINGS
        if isinstance(error, mapping.error_types)
    )


@pytest.fixture(autouse=True)
def restored_observability_id():
    """Undo the observability ID each submission binds in the test's context."""
    token = _asgi_observability_id.set(None)
    yield
    _asgi_observability_id.reset(token)


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

    with pytest.raises(SimulationServiceUnavailableError) as unreadable:
        service.client().submit(calculation_input())

    assert _route_status(unreadable.value) == 503
    assert str(unreadable.value) == (
        "The simulation service's answer could not be read."
    )


def test_a_field_refusal_with_a_code_that_is_not_text_keeps_its_reasons() -> None:
    service = RecordingService(
        422, {"code": 5, "detail": [{"loc": ["body", "spm"], "msg": "refused"}]}
    )

    with pytest.raises(SimulationServiceInvalidRequestError) as refused:
        service.client().submit(calculation_input())

    assert str(refused.value) == (
        "The simulation service cannot calculate this household: spm: refused"
    )


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


def test_a_refused_modal_call_gives_only_its_status_and_code() -> None:
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
        "The simulation service is unavailable (503 modal_call_refused)."
    )


def test_a_dependency_the_service_cannot_read_names_its_code() -> None:
    service = RecordingService(
        503, {"code": "database_unavailable", "detail": "The database is down"}
    )

    with pytest.raises(SimulationServiceUnavailableError) as refused:
        service.client().submit(calculation_input())

    # The service's text may hold stored data, so only its status and code
    # reach the caller.
    assert str(refused.value) == (
        "The simulation service is unavailable (503 database_unavailable)."
    )


@pytest.mark.parametrize(
    ("code", "shown"),
    [
        pytest.param("internal_error", "500 internal_error", id="kept"),
        pytest.param("a" * 64, f"500 {'a' * 64}", id="64-characters"),
        pytest.param("a" * 65, "500", id="65-characters"),
        pytest.param("Internal_error", "500", id="capital"),
        pytest.param("1st_failure", "500", id="leading-digit"),
        pytest.param("_failure", "500", id="leading-underscore"),
        pytest.param("internal-error", "500", id="hyphen"),
        pytest.param("internal error: row 7", "500", id="text"),
        pytest.param("internal_error\n", "500", id="trailing-newline"),
        pytest.param("", "500", id="empty"),
        pytest.param(5, "500", id="number"),
        pytest.param(None, "500", id="null"),
    ],
)
def test_only_a_code_that_is_a_fixed_identifier_is_shown(code, shown) -> None:
    service = RecordingService(500, {"code": code, "detail": "The household is 52000"})

    with pytest.raises(SimulationServiceInternalError) as failed:
        service.client().submit(calculation_input())

    assert str(failed.value) == created_but_failed_message(shown)


@pytest.mark.parametrize(
    "code",
    [
        pytest.param("Unknown Household", id="not-an-identifier"),
        pytest.param(5, id="number"),
        pytest.param(["unknown_household"], id="list"),
    ],
)
def test_a_refusal_code_that_is_not_a_fixed_identifier_is_left_out(code) -> None:
    service = RecordingService(400, {"code": code, "detail": "Household not found"})

    with pytest.raises(SimulationServiceUnavailableError) as refused:
        service.client().submit(calculation_input())

    assert str(refused.value) == (
        "The simulation service refused the calculation: Household not found"
    )


def test_a_refusal_without_a_textual_reason_gives_its_status_and_code() -> None:
    service = RecordingService(
        400,
        {"code": "unknown_household", "detail": [{"loc": ["body"], "msg": "x"}]},
    )

    with pytest.raises(SimulationServiceUnavailableError) as refused:
        service.client().submit(calculation_input())

    assert str(refused.value) == (
        "The simulation service refused the calculation (400 unknown_household)."
    )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        pytest.param(
            {
                "code": "internal_error",
                "detail": "The service could not build the household function's "
                "request.",
            },
            created_but_failed_message("500 internal_error"),
            id="internal-error",
        ),
        pytest.param(
            {"detail": "The service stopped."},
            created_but_failed_message("500"),
            id="no-code",
        ),
        pytest.param(b"", created_but_failed_message("500"), id="unreadable"),
    ],
)
def test_an_internal_error_is_not_unavailable(body, message) -> None:
    # A 500 may come after the service created the job, so the caller is told
    # that submitting again may create a second job. The service's text may
    # hold stored data, so only its status and code reach the caller.
    service = RecordingService(500, body)

    with pytest.raises(SimulationServiceInternalError) as failed:
        service.client().submit(calculation_input())

    assert _route_status(failed.value) == 502
    assert str(failed.value) == message


@pytest.mark.parametrize("status_code", [502, 504])
def test_a_proxys_answer_in_place_of_the_services_is_not_unavailable(
    status_code,
) -> None:
    # A proxy in front of the service, such as Cloud Run's front end, may
    # answer 502 or 504 after the service created the job.
    service = RecordingService(status_code, b"upstream request timeout")

    with pytest.raises(SimulationServiceAnswerUnreadableError) as lost:
        service.client().submit(calculation_input())

    assert _route_status(lost.value) == 502
    assert str(lost.value) == lost_answer_message(f"a proxy answered {status_code}")


@pytest.mark.parametrize(
    ("status_code", "body", "message"),
    [
        # The service's authentication, routing, body-size and rate limits
        # answer these before its route creates a job.
        *(
            pytest.param(
                status_code,
                b"",
                f"The simulation service is unavailable ({status_code}).",
                id=str(status_code),
            )
            for status_code in (401, 403, 404, 405, 413, 429)
        ),
        pytest.param(
            403,
            {"detail": "Forbidden"},
            "The simulation service is unavailable (403).",
            id="403-from-fastapi",
        ),
        pytest.param(
            400,
            b"",
            "The simulation service refused the calculation (400).",
            id="400",
        ),
    ],
)
def test_an_answer_given_before_a_job_is_created_is_unavailable(
    status_code, body, message
) -> None:
    service = RecordingService(status_code, body)

    with pytest.raises(SimulationServiceUnavailableError) as unavailable:
        service.client().submit(calculation_input())

    assert _route_status(unavailable.value) == 503
    assert str(unavailable.value) == message


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"<html>Service Unavailable</html>", id="html"),
        pytest.param({"detail": "Service Unavailable"}, id="no-code"),
        pytest.param({"code": "Not An Identifier", "detail": "x"}, id="bad-code"),
        pytest.param({"code": 7, "detail": "x"}, id="number-code"),
    ],
)
def test_a_503_without_the_services_code_came_from_a_proxy(body) -> None:
    # The service's own 503 always names its code. Without one, Cloud Run's
    # front end answered in its place, possibly after the service created the
    # job.
    service = RecordingService(503, body)

    with pytest.raises(SimulationServiceAnswerUnreadableError) as lost:
        service.client().submit(calculation_input())

    assert _route_status(lost.value) == 502
    assert str(lost.value) == lost_answer_message("a proxy answered 503")


@pytest.mark.parametrize(
    ("status_code", "body", "status_and_code"),
    [
        *(
            pytest.param(status_code, b"", str(status_code), id=str(status_code))
            for status_code in (199, 200, 201, 204, 302, 307, 408, 409, 410, 501, 600)
        ),
        pytest.param(
            409,
            {"code": "job_exists", "detail": "The household's income is 52000"},
            "409 job_exists",
            id="409-with-code",
        ),
    ],
)
def test_an_unexpected_answer_may_have_created_the_job(
    status_code, body, status_and_code
) -> None:
    # The service may have created the job before answering a status the
    # Public API does not expect, so the caller is not told that nothing was
    # created.
    service = RecordingService(status_code, body)

    with pytest.raises(SimulationServiceAnswerUnreadableError) as unexpected:
        service.client().submit(calculation_input())

    assert _route_status(unexpected.value) == 502
    assert str(unexpected.value) == created_but_failed_message(status_and_code)


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
    # told that submitting again creates a second job.
    service = RecordingService(202, body)

    with pytest.raises(SimulationServiceAnswerUnreadableError) as unreadable:
        service.client().submit(calculation_input())

    assert _route_status(unreadable.value) == 502
    assert str(unreadable.value) == created_but_failed_message("202")


def _client_raising(error_type: type[httpx.TransportError]):
    def fail(request: httpx.Request) -> httpx.Response:
        msg = "the transport failed"
        raise error_type(msg, request=request)

    return SimulationHouseholdCalculationClient.from_environment(
        transport=httpx.MockTransport(fail)
    )


@pytest.mark.parametrize(
    "error_type", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout]
)
def test_a_connection_never_made_is_unavailable(error_type) -> None:
    with pytest.raises(SimulationServiceUnavailableError, match="could not be reached"):
        _client_raising(error_type).submit(calculation_input())


@pytest.mark.parametrize(
    "error_type",
    [
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.ReadError,
        httpx.WriteError,
        httpx.RemoteProtocolError,
    ],
)
def test_an_answer_lost_after_sending_is_not_unavailable(error_type) -> None:
    # The service may have received the submission and created the job, so
    # the caller is told that submitting again may create a second job.
    with pytest.raises(SimulationServiceAnswerUnreadableError) as lost:
        _client_raising(error_type).submit(calculation_input())

    assert _route_status(lost.value) == 502
    assert str(lost.value) == lost_answer_message(error_type.__name__)


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
