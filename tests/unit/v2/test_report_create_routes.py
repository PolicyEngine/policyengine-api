"""Create v2 reports and simulations over stand-in services."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, NoReturn
from uuid import UUID

import httpx
import pytest

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.v2.reports.routes import REPORT_ERROR_MAPPINGS
from policyengine_api.fastapi_routes.v2.simulations.routes import (
    SIMULATION_ERROR_MAPPINGS,
)
from policyengine_api.libs.simulation_reports import SimulationServiceReportClient
from policyengine_api.services.v2.policies.validators import PolicyNotFoundError
from policyengine_api.services.v2.simulation_service.types import (
    SimulationServiceAnswerUnreadableError,
    SimulationServiceInternalError,
    SimulationServiceInvalidRequestError,
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.simulation_service.validators import (
    EconomyCalculationsUnsupportedError,
)
from policyengine_api.services.v2.stored_reports.services import (
    V2StoredReportService,
)
from policyengine_api.services.v2.stored_reports.validators import (
    CreatedReportUnreadableError,
)
from policyengine_api.services.v2.stored_simulations.services import (
    V2StoredSimulationService,
)
from policyengine_api.services.v2.stored_simulations.validators import (
    CreatedSimulationUnreadableError,
)
from tests.unit.v2.simulation_service_messages import (
    answer_lost_message,
    possibly_created_message,
)
from tests.unit.v2.stored_report_support import (
    CURRENT_VERSIONS,
    POLICY_ID,
    REPORT_ID,
    FakeReportService,
    FakeSimulationService,
    report_route_client,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi.testclient import TestClient

ROUTE_SUPPORT_LOGGER = "policyengine_api.fastapi_routes.v2.simulation_resources_support"


@pytest.fixture
def enabled_route_support_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable the report and simulation routes' logger for one test.

    Alembic's env.py runs logging.config.fileConfig, which disables every
    logger that already exists. Alembic tests run it in this process, after
    collection has imported the routes, so the logger may be disabled here.
    """
    monkeypatch.setattr(logging.getLogger(ROUTE_SUPPORT_LOGGER), "disabled", False)


def logged_events(caplog) -> list[str]:
    """Return the events the report and simulation routes logged."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == ROUTE_SUPPORT_LOGGER
    ]


def report_body(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "country_id": "us",
        "kind": "economy",
        "label": "Expanded child tax credit",
        "year": 2026,
        "region_code": "state/ca",
        "baseline": {},
        "reform": {"policy_id": str(POLICY_ID)},
    }
    return {**values, **changes}


def simulation_body(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "country_id": "us",
        "kind": "economy",
        "year": 2026,
        "region_code": "us",
        "policy_id": str(POLICY_ID),
    }
    return {**values, **changes}


def test_a_report_is_created_and_answered_as_stored() -> None:
    service = FakeReportService()

    response = report_route_client(reports=service).post(
        "/v2/reports?country_id=us",
        json=report_body(include_cliffs=True, spm={"geography_kind": "national"}),
    )

    assert response.status_code == 201, response.text
    assert response.json()["result"]["item"]["id"] == str(REPORT_ID)
    ((operation, arguments),) = service.calls
    assert operation == "create_report"
    created = arguments["report_input"]
    assert created.country_id == "us"
    assert created.include_cliffs is True
    assert created.reform.policy_id == POLICY_ID
    assert created.spm.geography_kind == "national"


def test_a_report_body_naming_another_country_is_refused() -> None:
    service = FakeReportService()

    response = report_route_client(reports=service).post(
        "/v2/reports?country_id=uk", json=report_body()
    )

    assert response.status_code == 400
    assert service.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {key: value for key, value in report_body().items() if key != "label"},
        report_body(kind="household"),
        report_body(year=2201),
        report_body(region_code="two words"),
        report_body(spm=None),
        report_body(include_cliffs="yes"),
        report_body(policyengine_version="4.2.0"),
        report_body(reform={"policy_id": "not-a-uuid"}),
    ],
    ids=[
        "no-label",
        "household-kind",
        "year-too-late",
        "region-with-space",
        "null-spm",
        "non-boolean-cliffs",
        "names-a-version",
        "malformed-policy",
    ],
)
def test_a_malformed_report_is_refused_before_the_service(
    body: dict[str, Any],
) -> None:
    service = FakeReportService()

    response = report_route_client(reports=service).post(
        "/v2/reports?country_id=us", json=body
    )

    assert response.status_code == 422
    assert service.calls == []


def test_a_report_body_over_16_kib_is_refused() -> None:
    service = FakeReportService()

    response = report_route_client(reports=service).post(
        "/v2/reports?country_id=us",
        json=report_body(description="x" * (17 * 1024)),
    )

    assert response.status_code == 413
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "status_code", "message"),
    [
        (
            PolicyNotFoundError("Policy p was not found in country 'us'"),
            404,
            "Policy p was not found in country 'us'",
        ),
        (
            EconomyCalculationsUnsupportedError(
                "Economy calculations are not available for country 'us'"
            ),
            422,
            "Economy calculations are not available for country 'us'",
        ),
        (
            SimulationServiceInvalidRequestError(
                "The simulation service cannot run this request (unknown_region): "
                "no such region"
            ),
            422,
            "The simulation service cannot run this request (unknown_region): "
            "no such region",
        ),
        (
            SimulationServiceInternalError(
                possibly_created_message("500 internal_error", "report")
            ),
            502,
            possibly_created_message("500 internal_error", "report"),
        ),
        (
            SimulationServiceAnswerUnreadableError(
                "The simulation service created the report, but its answer "
                "could not be read."
            ),
            502,
            "The simulation service created the report, but its answer could "
            "not be read.",
        ),
        (
            SimulationServiceUnavailableError(
                "The simulation service is unavailable (503 manifest_unavailable)."
            ),
            503,
            "The simulation service is unavailable (503 manifest_unavailable).",
        ),
    ],
    ids=[
        "policy-not-stored",
        "household-only",
        "service-refusal",
        "service-failure",
        "unreadable-answer",
        "service-unavailable",
    ],
)
def test_report_creation_failures_answer_typed_errors(
    error: Exception, status_code: int, message: str
) -> None:
    client = report_route_client(reports=FakeReportService(error=error))

    response = client.post("/v2/reports?country_id=us", json=report_body())

    assert response.status_code == status_code
    assert response.json() == {"status": "error", "message": message}


def test_a_simulation_is_created_and_answered_as_stored() -> None:
    service = FakeSimulationService()

    response = report_route_client(simulations=service).post(
        "/v2/simulations?country_id=us",
        json=simulation_body(dataset_name="enhanced_cps_2024"),
    )

    assert response.status_code == 201, response.text
    assert response.json()["result"]["item"]["id"] == str(service.simulation.id)
    ((operation, arguments),) = service.calls
    assert operation == "create_simulation"
    created = arguments["simulation_input"]
    assert created.dataset_name == "enhanced_cps_2024"
    assert created.policy_id == POLICY_ID


@pytest.mark.parametrize(
    ("query", "body", "status_code"),
    [
        ("country_id=uk", simulation_body(), 400),
        ("country_id=us", simulation_body(kind="household"), 422),
        ("country_id=us", simulation_body(year=1899), 422),
        ("country_id=us", simulation_body(include_cliffs=True), 422),
    ],
    ids=["other-country", "household-kind", "year-too-early", "report-option"],
)
def test_a_malformed_simulation_is_refused_before_the_service(
    query: str, body: dict[str, Any], status_code: int
) -> None:
    service = FakeSimulationService()

    response = report_route_client(simulations=service).post(
        f"/v2/simulations?{query}", json=body
    )

    assert response.status_code == status_code
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (PolicyNotFoundError("Policy p was not found"), 404),
        (EconomyCalculationsUnsupportedError("not available"), 422),
        (SimulationServiceInvalidRequestError("no such dataset"), 422),
        (SimulationServiceInternalError("failed"), 502),
        (SimulationServiceAnswerUnreadableError("answer lost"), 502),
        (SimulationServiceUnavailableError("unavailable"), 503),
    ],
    ids=["policy", "country", "refusal", "failure", "unreadable", "unavailable"],
)
def test_simulation_creation_failures_answer_typed_errors(
    error: Exception, status_code: int
) -> None:
    client = report_route_client(simulations=FakeSimulationService(error=error))

    response = client.post("/v2/simulations?country_id=us", json=simulation_body())

    assert response.status_code == status_code
    assert response.json()["message"] == str(error)


def test_a_created_report_that_cannot_be_read_back_answers_its_id() -> None:
    error = CreatedReportUnreadableError(report_id=REPORT_ID, country_id="us")
    client = report_route_client(reports=FakeReportService(error=error))

    response = client.post("/v2/reports?country_id=us", json=report_body())

    assert response.status_code == 502
    assert response.json() == {
        "status": "error",
        "message": (
            f"The simulation service created report {REPORT_ID}, but it could "
            f"not be read back. Read it with GET /v2/reports/{REPORT_ID}"
            "?country_id=us rather than submitting it again."
        ),
        "report_id": str(REPORT_ID),
    }


def test_a_created_simulation_that_cannot_be_read_back_answers_its_id() -> None:
    simulation_id = FakeSimulationService().simulation.id
    error = CreatedSimulationUnreadableError(
        simulation_id=simulation_id, country_id="us"
    )
    client = report_route_client(simulations=FakeSimulationService(error=error))

    response = client.post("/v2/simulations?country_id=us", json=simulation_body())

    assert response.status_code == 502
    assert response.json() == {
        "status": "error",
        "message": (
            f"The simulation service created simulation {simulation_id}, but it "
            f"could not be read back. Read it with GET /v2/simulations/"
            f"{simulation_id}?country_id=us rather than submitting it again."
        ),
        "simulation_id": str(simulation_id),
    }


@pytest.mark.usefixtures("enabled_route_support_logger")
def test_a_report_the_unavailable_service_created_answers_its_id(caplog) -> None:
    message = (
        f"The simulation service created report {REPORT_ID}, but is unavailable "
        "(503 modal_call_refused)."
    )
    error = SimulationServiceUnavailableError(message, created_record_id=REPORT_ID)
    client = report_route_client(reports=FakeReportService(error=error))

    with caplog.at_level("ERROR", logger=ROUTE_SUPPORT_LOGGER):
        response = client.post("/v2/reports?country_id=us", json=report_body())

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": message,
        "report_id": str(REPORT_ID),
    }
    assert logged_events(caplog) == ["v2_report_unavailable_after_creation"]


@pytest.mark.usefixtures("enabled_route_support_logger")
def test_a_simulation_the_unavailable_service_created_answers_its_id(
    caplog,
) -> None:
    simulation_id = FakeSimulationService().simulation.id
    message = (
        f"The simulation service created simulation {simulation_id}, but is "
        "unavailable (503 modal_call_refused)."
    )
    error = SimulationServiceUnavailableError(message, created_record_id=simulation_id)
    client = report_route_client(simulations=FakeSimulationService(error=error))

    with caplog.at_level("ERROR", logger=ROUTE_SUPPORT_LOGGER):
        response = client.post("/v2/simulations?country_id=us", json=simulation_body())

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": message,
        "simulation_id": str(simulation_id),
    }
    assert logged_events(caplog) == ["v2_simulation_unavailable_after_creation"]


@pytest.mark.parametrize(
    ("path", "status_code", "schema", "id_field"),
    [
        pytest.param(
            "/v2/reports",
            "502",
            "CreatedReportUnreadableResponse",
            "report_id",
            id="report-502",
        ),
        pytest.param(
            "/v2/simulations",
            "502",
            "CreatedSimulationUnreadableResponse",
            "simulation_id",
            id="simulation-502",
        ),
        pytest.param(
            "/v2/reports",
            "503",
            "UnavailableAfterReportCreatedResponse",
            "report_id",
            id="report-503",
        ),
        pytest.param(
            "/v2/simulations",
            "503",
            "UnavailableAfterSimulationCreatedResponse",
            "simulation_id",
            id="simulation-503",
        ),
    ],
)
def test_the_openapi_document_gives_the_created_records_id(
    path: str, status_code: str, schema: str, id_field: str
) -> None:
    document = report_route_client().get("/v2/openapi.json").json()

    answer = document["paths"][path]["post"]["responses"][status_code]
    assert {"$ref": f"#/components/schemas/{schema}"} in answer["content"][
        "application/json"
    ]["schema"]["anyOf"]
    assert document["components"]["schemas"][schema]["required"] == [
        "message",
        id_field,
    ]


@pytest.mark.parametrize(
    "error_mappings",
    [REPORT_ERROR_MAPPINGS, SIMULATION_ERROR_MAPPINGS],
    ids=["reports", "simulations"],
)
def test_no_error_mapping_is_shadowed_by_an_earlier_one(error_mappings) -> None:
    # The first matching mapping answers, so an error type an earlier mapping
    # already matches would never get its own answer.
    shadowed = [
        (error_type.__name__, mapping.message)
        for position, mapping in enumerate(error_mappings)
        for error_type in mapping.error_types
        if any(
            issubclass(error_type, earlier_type)
            for earlier in error_mappings[:position]
            for earlier_type in earlier.error_types
        )
    ]

    assert shadowed == []


@pytest.mark.parametrize(
    ("client_for_error", "method", "path", "body"),
    [
        pytest.param(
            lambda error: report_route_client(reports=FakeReportService(error=error)),
            "get",
            f"/v2/reports/{REPORT_ID}?country_id=us",
            None,
            id="report-read",
        ),
        pytest.param(
            lambda error: report_route_client(reports=FakeReportService(error=error)),
            "post",
            "/v2/reports?country_id=us",
            report_body(),
            id="report-create",
        ),
        pytest.param(
            lambda error: report_route_client(
                simulations=FakeSimulationService(error=error)
            ),
            "post",
            "/v2/simulations?country_id=us",
            simulation_body(),
            id="simulation-create",
        ),
    ],
)
def test_missing_v2_database_configuration_is_storage_unavailable(
    client_for_error, method: str, path: str, body: dict[str, Any] | None
) -> None:
    client = client_for_error(V2ConfigurationError("V2_DATABASE_URL is not set"))

    response = client.request(method, path, json=body)

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": "V2 storage is unavailable",
    }


SIMULATION_SERVICE_URL = "https://simulation.example.test"
# The record the simulation service names in its answers, and another record.
NAMED_RECORD_ID = UUID("00000000-0000-0000-0000-00000000c001")
OTHER_RECORD_ID = UUID("00000000-0000-0000-0000-00000000c002")
# The field naming each record in the simulation service's answers.
RECORD_ID_FIELDS = {"report": "report_id", "simulation": "simulation_id"}
# The field naming a record other than the submission's own.
OTHER_RECORD_ID_FIELDS = {"report": "simulation_id", "simulation": "report_id"}
RECORDS = ["report", "simulation"]


class UnreadDatabase:
    """The detailed-save database, which a failed submission never reads."""

    def read(self) -> NoReturn:
        msg = "The route read the database after the submission failed."
        raise AssertionError(msg)


def answering(
    status_code: int, body: object
) -> Callable[[httpx.Request], httpx.Response]:
    """Answer every request with ``status_code`` and ``body``; bytes as they are."""

    def answer(request: httpx.Request) -> httpx.Response:
        if isinstance(body, bytes):
            return httpx.Response(status_code, content=body)
        return httpx.Response(status_code, json=body)

    return answer


def losing_the_answer(request: httpx.Request) -> httpx.Response:
    """Fail as a read timeout does, after the request was sent."""
    msg = "the answer did not arrive"
    raise httpx.ReadTimeout(msg, request=request)


def modal_refusal_naming(id_field: str, record_id: str) -> dict[str, str]:
    """Return the simulation service's 503 after Modal refused, naming one record."""
    return {
        "code": "modal_call_refused",
        "detail": "Modal refused the call.",
        id_field: record_id,
    }


def post_through_simulation_service(
    record: str, answer: Callable[[httpx.Request], httpx.Response]
) -> httpx.Response:
    """Create ``record`` through the real client, its requests answered by ``answer``.

    The route's stored service sends through ``SimulationServiceReportClient``
    over a mock transport.
    """
    submissions = SimulationServiceReportClient(
        httpx.Client(
            base_url=SIMULATION_SERVICE_URL, transport=httpx.MockTransport(answer)
        )
    )
    client: TestClient
    if record == "report":
        client = report_route_client(
            reports=V2StoredReportService(
                UnreadDatabase(),
                current_versions=lambda _country_id: CURRENT_VERSIONS,
                submissions=submissions,
            )
        )
        return client.post("/v2/reports?country_id=us", json=report_body())
    client = report_route_client(
        simulations=V2StoredSimulationService(
            UnreadDatabase(),
            current_versions=lambda _country_id: CURRENT_VERSIONS,
            submissions=submissions,
        )
    )
    return client.post("/v2/simulations?country_id=us", json=simulation_body())


# A reason holding stored data, as an exception's text can.
EXCEPTION_TEXT = (
    "psycopg.errors.UniqueViolation: Key (label)=(Private household plan) "
    "already exists."
)
CREATED_BODIES = {
    "report": {
        "report_id": str(NAMED_RECORD_ID),
        "report_run_id": str(OTHER_RECORD_ID),
    },
    "simulation": {
        "simulation_id": str(NAMED_RECORD_ID),
        "simulation_run_id": str(OTHER_RECORD_ID),
    },
}


@pytest.mark.parametrize(
    ("answer", "stated_error"),
    [
        pytest.param(losing_the_answer, "ReadTimeout", id="answer-lost"),
        pytest.param(
            answering(502, b"Bad Gateway"),
            "a proxy answered 502 in its place",
            id="proxy-502",
        ),
        pytest.param(
            answering(504, b"upstream request timeout"),
            "a proxy answered 504 in its place",
            id="proxy-504",
        ),
    ],
)
@pytest.mark.parametrize("record", RECORDS)
def test_an_answer_lost_after_sending_answers_502(
    record: str,
    answer: Callable[[httpx.Request], httpx.Response],
    stated_error: str,
) -> None:
    # The service may have received the request and created the record, so
    # the answer is not a 503, which says it created nothing.
    response = post_through_simulation_service(record, answer)

    assert response.status_code == 502
    assert response.json() == {
        "status": "error",
        "message": answer_lost_message(stated_error, record),
    }


@pytest.mark.parametrize(
    ("answer_for_record", "status_and_code"),
    [
        pytest.param(
            lambda _record: answering(
                500,
                {"code": "internal_error", "detail": "The run could not be started."},
            ),
            "500 internal_error",
            id="500",
        ),
        pytest.param(
            lambda _record: answering(500, {"detail": "The run could not be started."}),
            "500",
            id="500-without-a-code",
        ),
        pytest.param(
            lambda _record: answering(500, b"Internal Server Error"),
            "500",
            id="unreadable-500",
        ),
        pytest.param(
            lambda _record: answering(
                503, b"upstream connect error or disconnect/reset before headers"
            ),
            "503",
            id="unreadable-503",
        ),
        pytest.param(
            lambda _record: answering(503, {"code": "modal_call_refused"}),
            "503 modal_call_refused",
            id="503-without-detail",
        ),
        pytest.param(
            lambda record: answering(
                503, modal_refusal_naming(RECORD_ID_FIELDS[record], "not-a-uuid")
            ),
            "503 modal_call_refused",
            id="503-malformed-record-id",
        ),
        pytest.param(
            lambda record: answering(
                503,
                modal_refusal_naming(
                    OTHER_RECORD_ID_FIELDS[record], str(OTHER_RECORD_ID)
                ),
            ),
            "503 modal_call_refused",
            id="503-naming-only-another-record",
        ),
        pytest.param(
            lambda record: answering(200, CREATED_BODIES[record]),
            "200",
            id="200-naming-the-record",
        ),
        pytest.param(lambda _record: answering(204, b""), "204", id="204"),
        pytest.param(
            lambda _record: answering(
                409, {"code": "label_taken", "detail": "The label is taken."}
            ),
            "409 label_taken",
            id="409-with-a-code",
        ),
    ],
)
@pytest.mark.parametrize("record", RECORDS)
def test_a_failure_that_may_follow_a_created_record_answers_502(
    record: str,
    answer_for_record: Callable[[str], Callable[[httpx.Request], httpx.Response]],
    status_and_code: str,
) -> None:
    # The service's route may have written rows before answering each of
    # these, so none is a 503, which says it created nothing.
    response = post_through_simulation_service(record, answer_for_record(record))

    assert response.status_code == 502
    assert response.json() == {
        "status": "error",
        "message": possibly_created_message(status_and_code, record),
    }


@pytest.mark.parametrize("record", RECORDS)
def test_a_503_naming_the_created_record_answers_503_with_its_id(record: str) -> None:
    id_field = RECORD_ID_FIELDS[record]
    answer = answering(503, modal_refusal_naming(id_field, str(NAMED_RECORD_ID)))

    response = post_through_simulation_service(record, answer)

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": (
            f"The simulation service created {record} {NAMED_RECORD_ID}, but is "
            "unavailable (503 modal_call_refused)."
        ),
        id_field: str(NAMED_RECORD_ID),
    }


@pytest.mark.parametrize("record", RECORDS)
def test_a_503_naming_both_records_answers_503_with_the_submissions_own_id(
    record: str,
) -> None:
    # A report's 503 may also name a simulation it created; the answer names
    # the submission's own record.
    id_field = RECORD_ID_FIELDS[record]
    answer = answering(
        503,
        {
            **modal_refusal_naming(id_field, str(NAMED_RECORD_ID)),
            OTHER_RECORD_ID_FIELDS[record]: str(OTHER_RECORD_ID),
        },
    )

    response = post_through_simulation_service(record, answer)

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": (
            f"The simulation service created {record} {NAMED_RECORD_ID}, but is "
            "unavailable (503 modal_call_refused)."
        ),
        id_field: str(NAMED_RECORD_ID),
    }


@pytest.mark.parametrize("record", RECORDS)
def test_a_503_naming_no_record_answers_503(record: str) -> None:
    answer = answering(
        503,
        {
            "code": "manifest_unavailable",
            "detail": "The v2 version manifest could not be read.",
        },
    )

    response = post_through_simulation_service(record, answer)

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": "The simulation service is unavailable (503 manifest_unavailable).",
    }


@pytest.mark.parametrize("status_code", [401, 403, 404, 405, 413, 429])
@pytest.mark.parametrize("record", RECORDS)
def test_a_status_sent_before_the_services_route_runs_answers_503(
    record: str, status_code: int
) -> None:
    # The gateway, Cloud Run or the service's framework answers these before
    # the service's route runs, so nothing was created.
    response = post_through_simulation_service(
        record, answering(status_code, {"detail": "Not Found"})
    )

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": f"The simulation service is unavailable ({status_code}).",
    }


@pytest.mark.parametrize(
    ("status_code", "record_named", "answer_status"),
    [
        pytest.param(500, None, 502, id="500"),
        pytest.param(503, None, 503, id="503-naming-no-record"),
        pytest.param(503, "own", 503, id="503-naming-the-record"),
        pytest.param(503, "other", 502, id="503-naming-another-record"),
    ],
)
@pytest.mark.parametrize("record", RECORDS)
def test_the_services_failure_reason_never_reaches_the_caller(
    record: str, status_code: int, record_named: str | None, answer_status: int
) -> None:
    # A 500's or 503's reason may be an exception's text holding stored data,
    # which must not reach an anonymous caller. Only the code is passed on.
    body = {"code": "internal_error", "detail": EXCEPTION_TEXT}
    if record_named == "own":
        body[RECORD_ID_FIELDS[record]] = str(NAMED_RECORD_ID)
    if record_named == "other":
        body[OTHER_RECORD_ID_FIELDS[record]] = str(OTHER_RECORD_ID)

    response = post_through_simulation_service(record, answering(status_code, body))

    assert response.status_code == answer_status
    assert f"({status_code} internal_error)" in response.json()["message"]
    assert "Private household plan" not in response.text
    assert "psycopg" not in response.text


@pytest.mark.parametrize(
    ("status_code", "body", "answer_status", "message"),
    [
        pytest.param(
            422,
            {"detail": "spm settings apply only to the US"},
            422,
            "The simulation service cannot run this request: spm settings apply "
            "only to the US",
            id="422",
        ),
        pytest.param(
            400,
            {
                "code": "unknown_region",
                "detail": "Region state/zz is not in the catalog version.",
            },
            422,
            "The simulation service cannot run this request (unknown_region): "
            "Region state/zz is not in the catalog version.",
            id="400-for-the-callers-region",
        ),
        pytest.param(
            400,
            {
                "code": "unknown_catalog_version",
                "detail": "Country us has no catalog version for .py 4.2.0.",
            },
            503,
            "The simulation service refused the {record} (unknown_catalog_version): "
            "Country us has no catalog version for .py 4.2.0.",
            id="400-for-the-services-state",
        ),
    ],
)
@pytest.mark.parametrize("record", RECORDS)
def test_a_refusal_gives_the_services_code_and_reason_but_not_its_status(
    record: str,
    status_code: int,
    body: dict[str, str],
    answer_status: int,
    message: str,
) -> None:
    # A 400's or 422's code and reason are passed on, but not its status,
    # since the route answers with its own.
    response = post_through_simulation_service(record, answering(status_code, body))

    assert response.status_code == answer_status
    assert response.json() == {
        "status": "error",
        "message": message.format(record=record),
    }


# Codes that are not a fixed identifier (lower-case letters, digits and
# underscores, starting with a letter, at most 64 characters), so a 500's or
# 503's message leaves them out.
CODES_LEFT_OUT = [
    pytest.param(EXCEPTION_TEXT, id="exception-text"),
    pytest.param("", id="empty"),
    pytest.param("Internal_Error", id="capital-letters"),
    pytest.param("5xx_error", id="starting-with-a-digit"),
    pytest.param("modal-call-refused", id="hyphenated"),
    pytest.param("internal_error\n", id="ending-in-a-newline"),
    pytest.param("a" * 65, id="65-characters"),
]


def without_a_code_answer(
    record: str, status_code: int, record_named: str | None
) -> tuple[int, dict[str, str]]:
    """Return the route's status and JSON for a failure whose code is left out."""
    if status_code != 503:
        return 502, {
            "status": "error",
            "message": possibly_created_message(str(status_code), record),
        }
    if record_named is None:
        return 503, {
            "status": "error",
            "message": "The simulation service is unavailable (503).",
        }
    return 503, {
        "status": "error",
        "message": (
            f"The simulation service created {record} {NAMED_RECORD_ID}, but is "
            "unavailable (503)."
        ),
        RECORD_ID_FIELDS[record]: str(NAMED_RECORD_ID),
    }


@pytest.mark.parametrize("code", CODES_LEFT_OUT)
@pytest.mark.parametrize(
    ("status_code", "record_named"),
    [
        pytest.param(500, None, id="500"),
        pytest.param(409, None, id="unexpected-409"),
        pytest.param(503, None, id="503-naming-no-record"),
        pytest.param(503, "own", id="503-naming-the-record"),
    ],
)
@pytest.mark.parametrize("record", RECORDS)
def test_a_code_that_is_not_a_fixed_identifier_is_left_out(
    record: str, status_code: int, record_named: str | None, code: str
) -> None:
    # A 500's or 503's code is passed on without its reason, so it must not
    # carry what the reason could: an exception's text, holding stored data.
    body = {"code": code, "detail": "The run failed."}
    if record_named == "own":
        body[RECORD_ID_FIELDS[record]] = str(NAMED_RECORD_ID)

    response = post_through_simulation_service(record, answering(status_code, body))

    answer_status, answer = without_a_code_answer(record, status_code, record_named)
    assert response.status_code == answer_status
    assert response.json() == answer


@pytest.mark.parametrize(
    "code",
    [
        pytest.param("a" * 64, id="64-characters"),
        pytest.param("modal_call_refused_2", id="letters-digits-and-underscores"),
    ],
)
@pytest.mark.parametrize("record", RECORDS)
def test_a_code_that_is_a_fixed_identifier_is_passed_on(record: str, code: str) -> None:
    answer = answering(503, {"code": code, "detail": "The run failed."})

    response = post_through_simulation_service(record, answer)

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": f"The simulation service is unavailable (503 {code}).",
    }
