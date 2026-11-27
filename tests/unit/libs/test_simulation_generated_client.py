"""API v1 sends each request to the simulation service through its generated client.

``policyengine-api-simulation-client`` is generated from the simulation
service's OpenAPI document. For each route API v1 calls, these tests check
that the request API v1 sends is the one the route's generated operation
builds from its generated request model, and that it is still the request
API v1 built by hand: the same method, URL, content type and JSON body.

They also check that API v1 still reads the answers that the generated
operations' own parsers raise on: a body that is not JSON, or not the shape
the route documents, and a status ``http.HTTPStatus`` doesn't name. The
generated ``create_report`` and ``rerun_report`` document only 201 for a
created record, so a 202 is checked too.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
import pytest
from policyengine_api_simulation_client.api.default import (
    create_report,
    create_simulation,
    rerun_report,
    submit_household_calculation,
)
from policyengine_api_simulation_client.models import (
    BudgetWindowReportRequest,
    EconomyReportRequest,
    EconomySimulationRequest,
    HouseholdCalculationRequest,
    HouseholdReportRequest,
    ReportRerunRequest,
)

from policyengine_api.libs.simulation_household_calculations import (
    SimulationHouseholdCalculationClient,
    household_calculation_request,
)
from policyengine_api.libs.simulation_report_reruns import report_rerun_request
from policyengine_api.libs.simulation_reports import (
    SimulationServiceReportClient,
    budget_window_request,
    household_report_request,
    report_request,
    simulation_request,
)
from policyengine_api.libs.simulation_service_answers import (
    simulation_service_http_client,
)
from policyengine_api.libs.simulation_service_operations import (
    post_household_calculation,
    post_report,
    post_report_rerun,
    post_simulation,
)
from policyengine_api.request_context import _asgi_observability_id
from policyengine_api.services.v2.household_calculations.types import (
    HouseholdCalculationAccepted,
)
from policyengine_api.services.v2.simulation_service.types import (
    SimulationServiceAnswerUnreadableError,
    SimulationServiceUnavailableError,
    StartedReportRun,
    SubmittedBudgetWindow,
    SubmittedReport,
    SubmittedSimulation,
)
from tests.fixtures.household_calculation_documents import JOB_ID
from tests.unit.libs.test_simulation_budget_window_reports import (
    BUDGET_WINDOW_RUN_ID,
    WINDOW_CREATED,
    window_input,
)
from tests.unit.libs.test_simulation_household_calculations import (
    created_but_failed_message,
    lost_answer_message,
)
from tests.unit.libs.test_simulation_household_report_requests import (
    OTHER_DYNAMIC_ID,
    household_report_input,
)
from tests.unit.libs.test_simulation_report_reruns import (
    RERUN_STARTED,
    possibly_started_message,
    rerun_input,
)
from tests.unit.libs.test_simulation_reports import (
    DYNAMIC_ID,
    POLICY_ID,
    REPORT_CREATED,
    REPORT_ID,
    REPORT_RUN_ID,
    SIMULATION_CREATED,
    SIMULATION_ID,
    SIMULATION_RUN_ID,
    report_input,
    simulation_input,
)
from tests.unit.v2.household_calculation_support import calculation_input
from tests.unit.v2.simulation_service_messages import possibly_created_message

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

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
# The generated models of the request bodies API v1 sends.
GENERATED_REQUEST_MODELS = (
    HouseholdCalculationRequest,
    EconomySimulationRequest,
    EconomyReportRequest,
    BudgetWindowReportRequest,
    HouseholdReportRequest,
    ReportRerunRequest,
)
# SPM settings naming every option, and settings naming options as null.
EVERY_SPM_OPTION = {
    "forecast_content_sha256": "a" * 64,
    "scenario": "ce_trend",
    "geography_kind": "metro",
    "geography_id": "31080",
    "county_vintage": "2020",
    "as_of": "2026-01-31",
}
NULL_SPM_OPTIONS = {"scenario": None, "as_of": None, "geography_kind": "national"}
HOUSEHOLD_JOB_ACCEPTED = {"job_id": str(JOB_ID), "status": "pending"}
# A front end's own error page, which is not JSON.
FRONT_END_PAGE = b"<html><body>Service Unavailable</body></html>"
# A status http.HTTPStatus doesn't name, so the generated Response refuses it.
UNNAMED_STATUS = 599


@pytest.fixture(autouse=True)
def configured_simulation_service(monkeypatch):
    """Name the Cloud Run simulation service; set no gateway credentials."""
    for name in ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SIMULATION_ENTRYPOINT_URL", f"{SIMULATION_URL}/")
    monkeypatch.setenv("SIM_ENTRYPOINT", "old_gateway_direct")
    monkeypatch.setenv("OLD_SIMULATION_GATEWAY_URL", "https://old.example.test")


@pytest.fixture(autouse=True)
def restored_observability_id():
    """Undo the observability ID each household submission binds."""
    token = _asgi_observability_id.set(None)
    yield
    _asgi_observability_id.reset(token)


@dataclass(frozen=True)
class Serialization:
    """A request body a generated request model wrote, and the model's name."""

    model_name: str
    body: dict[str, Any]


def _recording_to_dict(
    original: Callable[[Any], dict[str, Any]], serializations: list[Serialization]
) -> Callable[[Any], dict[str, Any]]:
    def to_dict(model: Any) -> dict[str, Any]:
        body = original(model)
        serializations.append(Serialization(type(model).__name__, body))
        return body

    return to_dict


@contextmanager
def recorded_serializations() -> Iterator[list[Serialization]]:
    """Record each body a generated request model writes inside the block."""
    serializations: list[Serialization] = []
    with pytest.MonkeyPatch.context() as patch:
        for model in GENERATED_REQUEST_MODELS:
            patch.setattr(
                model, "to_dict", _recording_to_dict(model.to_dict, serializations)
            )
        yield serializations


class ScriptedService:
    """The simulation service, answering every request with one scripted answer."""

    def __init__(self, status_code: int, body: object) -> None:
        self.status_code = status_code
        self.body = body
        self.requests: list[httpx.Request] = []

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.body, bytes):
            return httpx.Response(self.status_code, content=self.body)
        return httpx.Response(self.status_code, json=self.body)

    def household_client(self) -> SimulationHouseholdCalculationClient:
        return SimulationHouseholdCalculationClient.from_environment(
            transport=httpx.MockTransport(self.answer)
        )

    def report_client(self) -> SimulationServiceReportClient:
        return SimulationServiceReportClient.from_environment(
            transport=httpx.MockTransport(self.answer)
        )

    def sent_request(self) -> httpx.Request:
        (request,) = self.requests
        return request


def generated_request(request_arguments: dict[str, Any]) -> httpx.Request:
    """Return the request a generated operation's arguments make at the service."""
    return httpx.Client(base_url=SIMULATION_URL).build_request(**request_arguments)


def assert_sent_through_generated_operation(
    sent: httpx.Request,
    serializations: list[Serialization],
    *,
    expected: httpx.Request,
    model_name: str,
    hand_built_body: dict[str, Any],
) -> None:
    """Check the sent request is the generated operation's and the hand-built one.

    ``expected`` is the request the generated operation builds from the
    generated model of ``hand_built_body``, the body API v1 builds by hand.
    """
    sent_body = json.loads(sent.content)
    assert serializations == [Serialization(model_name, sent_body)], (
        f"API v1 did not send the body {model_name} wrote"
    )
    assert sent.method == expected.method
    assert sent.url == expected.url
    assert sent.headers["Content-Type"] == expected.headers["Content-Type"]
    assert sent.content == expected.content
    assert sent_body == hand_built_body


HOUSEHOLD_CALCULATION_CHANGES = {
    "current law": {"policy_id": None},
    "a reform": {},
    "every option": {
        "dynamic_id": DYNAMIC_ID,
        "add_missing_variables": True,
        "axes": [
            [{"name": "employment_income", "count": 3, "min": 0, "max": 90_000.5}],
            [
                {
                    "name": "age",
                    "count": 2,
                    "min": 20,
                    "max": 60,
                    "period": "2026",
                    "index": 1,
                }
            ],
        ],
        "spm": EVERY_SPM_OPTION,
    },
    "options named as null": {
        "axes": [
            [
                {
                    "name": "employment_income",
                    "count": 2,
                    "min": 0,
                    "max": 1,
                    "period": None,
                    "index": None,
                }
            ]
        ],
        "spm": NULL_SPM_OPTIONS,
    },
}


@pytest.mark.parametrize("case", list(HOUSEHOLD_CALCULATION_CHANGES))
def test_a_household_calculation_is_sent_by_the_generated_operation(
    case: str,
) -> None:
    calculation = calculation_input(**HOUSEHOLD_CALCULATION_CHANGES[case])
    hand_built_body = household_calculation_request(calculation)
    expected = generated_request(
        submit_household_calculation._get_kwargs(
            body=HouseholdCalculationRequest.from_dict(hand_built_body)
        )
    )
    service = ScriptedService(202, HOUSEHOLD_JOB_ACCEPTED)

    with recorded_serializations() as serializations:
        accepted = service.household_client().submit(calculation)

    assert accepted == HouseholdCalculationAccepted(
        calculation_id=JOB_ID, status="pending"
    )
    assert_sent_through_generated_operation(
        service.sent_request(),
        serializations,
        expected=expected,
        model_name="HouseholdCalculationRequest",
        hand_built_body=hand_built_body,
    )


@pytest.mark.parametrize(
    ("status_code", "body", "error_type", "message"),
    [
        pytest.param(
            202,
            b"not json",
            SimulationServiceAnswerUnreadableError,
            created_but_failed_message("202"),
            id="accepted, not JSON",
        ),
        pytest.param(
            202,
            {"job_id": str(JOB_ID)},
            SimulationServiceAnswerUnreadableError,
            created_but_failed_message("202"),
            id="accepted, without a status",
        ),
        pytest.param(
            400,
            ["not", "an", "object"],
            SimulationServiceUnavailableError,
            "The simulation service refused the calculation (400).",
            id="refused, not an object",
        ),
        pytest.param(
            422,
            b"not json",
            SimulationServiceUnavailableError,
            "The simulation service's answer could not be read.",
            id="unprocessable, not JSON",
        ),
        pytest.param(
            503,
            FRONT_END_PAGE,
            SimulationServiceAnswerUnreadableError,
            lost_answer_message("a proxy answered 503"),
            id="a front end's 503",
        ),
        pytest.param(
            UNNAMED_STATUS,
            b"",
            SimulationServiceAnswerUnreadableError,
            created_but_failed_message(str(UNNAMED_STATUS)),
            id="a status HTTPStatus doesn't name",
        ),
    ],
)
def test_household_calculation_answers_the_generated_parser_refuses_are_read(
    status_code: int, body: object, error_type: type[Exception], message: str
) -> None:
    service = ScriptedService(status_code, body)

    with (
        recorded_serializations() as serializations,
        pytest.raises(error_type) as raised,
    ):
        service.household_client().submit(calculation_input())

    assert str(raised.value) == message
    assert [serialization.model_name for serialization in serializations] == [
        "HouseholdCalculationRequest"
    ]


SIMULATION_CHANGES = {
    "current law": {"policy_id": None},
    "a reform": {},
    "a reform and a dynamic": {"dynamic_id": str(DYNAMIC_ID)},
}


@pytest.mark.parametrize("case", list(SIMULATION_CHANGES))
def test_a_simulation_is_sent_by_the_generated_operation(case: str) -> None:
    simulation = simulation_input(**SIMULATION_CHANGES[case])
    hand_built_body = simulation_request(simulation)
    expected = generated_request(
        create_simulation._get_kwargs(
            body=EconomySimulationRequest.from_dict(hand_built_body)
        )
    )
    service = ScriptedService(201, SIMULATION_CREATED)

    with recorded_serializations() as serializations:
        submitted = service.report_client().submit_simulation(simulation)

    assert submitted == SubmittedSimulation(
        simulation_id=SIMULATION_ID, simulation_run_id=SIMULATION_RUN_ID
    )
    assert_sent_through_generated_operation(
        service.sent_request(),
        serializations,
        expected=expected,
        model_name="EconomySimulationRequest",
        hand_built_body=hand_built_body,
    )


@pytest.mark.parametrize(
    ("status_code", "body", "error_type", "message"),
    [
        pytest.param(
            201,
            b"not json",
            SimulationServiceAnswerUnreadableError,
            "The simulation service created the simulation, but its answer "
            "could not be read.",
            id="created, not JSON",
        ),
        pytest.param(
            422,
            b"not json",
            SimulationServiceUnavailableError,
            "The simulation service answered 422 unreadably.",
            id="unprocessable, not JSON",
        ),
        pytest.param(
            503,
            FRONT_END_PAGE,
            SimulationServiceAnswerUnreadableError,
            possibly_created_message("503", "simulation"),
            id="a front end's 503",
        ),
        pytest.param(
            UNNAMED_STATUS,
            b"",
            SimulationServiceAnswerUnreadableError,
            possibly_created_message(str(UNNAMED_STATUS), "simulation"),
            id="a status HTTPStatus doesn't name",
        ),
    ],
)
def test_simulation_answers_the_generated_parser_refuses_are_read(
    status_code: int, body: object, error_type: type[Exception], message: str
) -> None:
    service = ScriptedService(status_code, body)

    with (
        recorded_serializations() as serializations,
        pytest.raises(error_type) as raised,
    ):
        service.report_client().submit_simulation(simulation_input())

    assert str(raised.value) == message
    assert [serialization.model_name for serialization in serializations] == [
        "EconomySimulationRequest"
    ]


@dataclass(frozen=True)
class ReportCase:
    """A report API v1 submits, how it builds the body, and its generated model."""

    submit: Callable[[SimulationServiceReportClient], object]
    hand_built_body: Callable[[], dict[str, Any]]
    generated_model: type[
        EconomyReportRequest | BudgetWindowReportRequest | HouseholdReportRequest
    ]
    created: dict[str, Any]
    submitted: object


def economy_report_case(**changes: Any) -> ReportCase:
    return ReportCase(
        submit=lambda client: client.submit_report(report_input(**changes)),
        hand_built_body=lambda: report_request(report_input(**changes)),
        generated_model=EconomyReportRequest,
        created=REPORT_CREATED,
        submitted=SubmittedReport(report_id=REPORT_ID, report_run_id=REPORT_RUN_ID),
    )


def budget_window_case(**changes: Any) -> ReportCase:
    return ReportCase(
        submit=lambda client: client.submit_budget_window(window_input(**changes)),
        hand_built_body=lambda: budget_window_request(window_input(**changes)),
        generated_model=BudgetWindowReportRequest,
        created=WINDOW_CREATED,
        submitted=SubmittedBudgetWindow(
            report_id=UUID(WINDOW_CREATED["report_id"]),
            budget_window_run_id=BUDGET_WINDOW_RUN_ID,
        ),
    )


def household_report_case(**changes: Any) -> ReportCase:
    return ReportCase(
        submit=lambda client: client.submit_household_report(
            household_report_input(**changes)
        ),
        hand_built_body=lambda: household_report_request(
            household_report_input(**changes)
        ),
        generated_model=HouseholdReportRequest,
        created=REPORT_CREATED,
        submitted=SubmittedReport(report_id=REPORT_ID, report_run_id=REPORT_RUN_ID),
    )


REPORT_CASES = {
    "an economy report": economy_report_case(),
    "an economy report with every option": economy_report_case(
        baseline={"dynamic_id": str(DYNAMIC_ID)},
        reform={"policy_id": str(POLICY_ID), "dynamic_id": str(DYNAMIC_ID)},
        include_cliffs=True,
        spm=EVERY_SPM_OPTION,
        data_source="local_area_dataset",
        region_code="country/wales",
        country_id="uk",
    ),
    "an economy report with SPM options named as null": economy_report_case(
        spm=NULL_SPM_OPTIONS
    ),
    "a budget window": budget_window_case(),
    "a budget window with SPM settings and dynamics": budget_window_case(
        baseline={"dynamic_id": str(DYNAMIC_ID)},
        spm=EVERY_SPM_OPTION,
    ),
    "a household report of the baseline alone": household_report_case(reform=None),
    "a household report": household_report_case(),
    "a household report with dynamics": household_report_case(
        baseline={"dynamic_id": str(DYNAMIC_ID)},
        reform={"policy_id": str(POLICY_ID), "dynamic_id": str(OTHER_DYNAMIC_ID)},
    ),
}


@pytest.mark.parametrize("case", list(REPORT_CASES))
def test_a_report_is_sent_by_the_generated_operation(case: str) -> None:
    report = REPORT_CASES[case]
    hand_built_body = report.hand_built_body()
    expected = generated_request(
        create_report._get_kwargs(
            body=report.generated_model.from_dict(hand_built_body)
        )
    )
    service = ScriptedService(201, report.created)

    with recorded_serializations() as serializations:
        submitted = report.submit(service.report_client())

    assert submitted == report.submitted
    assert_sent_through_generated_operation(
        service.sent_request(),
        serializations,
        expected=expected,
        model_name=report.generated_model.__name__,
        hand_built_body=hand_built_body,
    )


@pytest.mark.parametrize(
    "case", ["an economy report", "a budget window", "a household report"]
)
def test_a_report_created_with_202_is_read(case: str) -> None:
    report = REPORT_CASES[case]
    service = ScriptedService(202, report.created)

    with recorded_serializations() as serializations:
        submitted = report.submit(service.report_client())

    assert submitted == report.submitted
    assert [serialization.model_name for serialization in serializations] == [
        report.generated_model.__name__
    ]


@pytest.mark.parametrize(
    ("case", "status_code", "body", "error_type", "message"),
    [
        pytest.param(
            "an economy report",
            201,
            b"not json",
            SimulationServiceAnswerUnreadableError,
            "The simulation service created the report, but its answer could "
            "not be read.",
            id="economy report created, not JSON",
        ),
        pytest.param(
            "a budget window",
            201,
            {"report_id": str(REPORT_ID)},
            SimulationServiceAnswerUnreadableError,
            "The simulation service created the budget window, but its answer "
            "could not be read.",
            id="budget window created, without its run",
        ),
        pytest.param(
            "a household report",
            201,
            [],
            SimulationServiceAnswerUnreadableError,
            "The simulation service created the report, but its answer could "
            "not be read.",
            id="household report created, not an object",
        ),
        pytest.param(
            "an economy report",
            400,
            b"not json",
            SimulationServiceUnavailableError,
            "The simulation service answered 400 unreadably.",
            id="refused, not JSON",
        ),
        pytest.param(
            "an economy report",
            503,
            FRONT_END_PAGE,
            SimulationServiceAnswerUnreadableError,
            possibly_created_message("503", "report"),
            id="a front end's 503",
        ),
        pytest.param(
            "a budget window",
            UNNAMED_STATUS,
            b"",
            SimulationServiceAnswerUnreadableError,
            possibly_created_message(str(UNNAMED_STATUS), "report"),
            id="a status HTTPStatus doesn't name",
        ),
    ],
)
def test_report_answers_the_generated_parser_refuses_are_read(
    case: str,
    status_code: int,
    body: object,
    error_type: type[Exception],
    message: str,
) -> None:
    report = REPORT_CASES[case]
    service = ScriptedService(status_code, body)

    with (
        recorded_serializations() as serializations,
        pytest.raises(error_type) as raised,
    ):
        report.submit(service.report_client())

    assert str(raised.value) == message
    assert [serialization.model_name for serialization in serializations] == [
        report.generated_model.__name__
    ]


RERUN_CHANGES = {
    "without force": {"force": False},
    "with force": {"force": True},
    "with cliffs": {"include_cliffs": True},
    "with force and cliffs": {"force": True, "include_cliffs": True},
}
STARTED_RUN = StartedReportRun(
    report_run_id=UUID(RERUN_STARTED["report_run_id"]),
    budget_window_run_id=None,
)


@pytest.mark.parametrize("case", list(RERUN_CHANGES))
def test_a_rerun_is_sent_by_the_generated_operation(case: str) -> None:
    rerun = rerun_input(**RERUN_CHANGES[case])
    hand_built_body = report_rerun_request(rerun)
    expected = generated_request(
        rerun_report._get_kwargs(
            rerun.report_id, body=ReportRerunRequest.from_dict(hand_built_body)
        )
    )
    service = ScriptedService(201, RERUN_STARTED)

    with recorded_serializations() as serializations:
        started = service.report_client().rerun_report(rerun)

    assert started == STARTED_RUN
    assert_sent_through_generated_operation(
        service.sent_request(),
        serializations,
        expected=expected,
        model_name="ReportRerunRequest",
        hand_built_body=hand_built_body,
    )


@pytest.mark.parametrize(
    ("status_code", "body", "error_type", "message"),
    [
        pytest.param(
            201,
            b"not json",
            SimulationServiceAnswerUnreadableError,
            "The simulation service answered that it started a new run of the "
            "report, but its answer could not be read. Read the report to see "
            "whether it has a new run before running it again.",
            id="started, not JSON",
        ),
        pytest.param(
            409,
            b"not json",
            SimulationServiceUnavailableError,
            "The simulation service answered 409 unreadably.",
            id="conflict, not JSON",
        ),
        pytest.param(
            503,
            FRONT_END_PAGE,
            SimulationServiceAnswerUnreadableError,
            possibly_started_message("503"),
            id="a front end's 503",
        ),
        pytest.param(
            UNNAMED_STATUS,
            b"",
            SimulationServiceAnswerUnreadableError,
            possibly_started_message(str(UNNAMED_STATUS)),
            id="a status HTTPStatus doesn't name",
        ),
    ],
)
def test_rerun_answers_the_generated_parser_refuses_are_read(
    status_code: int, body: object, error_type: type[Exception], message: str
) -> None:
    service = ScriptedService(status_code, body)

    with (
        recorded_serializations() as serializations,
        pytest.raises(error_type) as raised,
    ):
        service.report_client().rerun_report(rerun_input())

    assert str(raised.value) == message
    assert [serialization.model_name for serialization in serializations] == [
        "ReportRerunRequest"
    ]


def test_a_rerun_started_with_202_is_read() -> None:
    service = ScriptedService(202, RERUN_STARTED)

    with recorded_serializations() as serializations:
        started = service.report_client().rerun_report(rerun_input())

    assert started == STARTED_RUN
    assert [serialization.model_name for serialization in serializations] == [
        "ReportRerunRequest"
    ]


def send_rerun(http_client: httpx.Client, body: dict[str, Any]) -> object:
    return post_report_rerun(http_client, rerun_input().report_id, body)


@pytest.mark.parametrize(
    ("send", "hand_built_body", "changed_field"),
    [
        pytest.param(
            post_household_calculation,
            {
                **household_calculation_request(calculation_input()),
                "field_the_model_lacks": 1,
            },
            "field_the_model_lacks",
            id="household calculation, a field the model lacks",
        ),
        pytest.param(
            post_simulation,
            {
                **simulation_request(simulation_input()),
                "field_the_model_lacks": 1,
            },
            "field_the_model_lacks",
            id="simulation, a field the model lacks",
        ),
        pytest.param(
            post_report,
            {**report_request(report_input()), "field_the_model_lacks": 1},
            "field_the_model_lacks",
            id="economy report, a field the model lacks",
        ),
        pytest.param(
            post_report,
            {
                **budget_window_request(window_input()),
                "spm": {"geography_kind": "national", "option_the_model_lacks": 1},
            },
            "spm",
            id="budget window, an SPM option the model lacks",
        ),
        pytest.param(
            post_report,
            {
                **household_report_request(household_report_input()),
                "reform": {"policy_id": str(POLICY_ID), "field_the_model_lacks": 1},
            },
            "reform",
            id="household report, a side's field the model lacks",
        ),
        pytest.param(
            send_rerun,
            {**report_rerun_request(rerun_input()), "field_the_model_lacks": 1},
            "field_the_model_lacks",
            id="rerun, a field the model lacks",
        ),
    ],
)
def test_a_body_the_generated_model_would_change_is_not_sent(
    send: Callable[[httpx.Client, dict[str, Any]], object],
    hand_built_body: dict[str, Any],
    changed_field: str,
) -> None:
    service = ScriptedService(201, {})
    http_client = simulation_service_http_client(
        transport=httpx.MockTransport(service.answer)
    )

    with pytest.raises(ValueError, match=changed_field):
        send(http_client, hand_built_body)

    assert service.requests == []
