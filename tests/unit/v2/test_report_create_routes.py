"""Create v2 reports and simulations over stand-in services."""

from __future__ import annotations

from typing import Any

import pytest

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.v2.reports.routes import REPORT_ERROR_MAPPINGS
from policyengine_api.fastapi_routes.v2.simulations.routes import (
    SIMULATION_ERROR_MAPPINGS,
)
from policyengine_api.services.v2.policies.validators import PolicyNotFoundError
from policyengine_api.services.v2.simulation_service.types import (
    SimulationServiceAnswerUnreadableError,
    SimulationServiceInternalError,
    SimulationServiceRefusalError,
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.simulation_service.validators import (
    EconomyCalculationsUnsupportedError,
)
from policyengine_api.services.v2.stored_reports.validators import (
    CreatedReportUnreadableError,
)
from policyengine_api.services.v2.stored_simulations.validators import (
    CreatedSimulationUnreadableError,
)
from tests.unit.v2.stored_report_support import (
    POLICY_ID,
    REPORT_ID,
    FakeReportService,
    FakeSimulationService,
    report_route_client,
)


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
            SimulationServiceRefusalError(
                "The simulation service cannot run this request: no such region"
            ),
            422,
            "The simulation service cannot run this request: no such region",
        ),
        (
            SimulationServiceInternalError("The simulation service failed"),
            502,
            "The simulation service failed",
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
            SimulationServiceUnavailableError("The simulation service answered 503."),
            503,
            "The simulation service answered 503.",
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
        (SimulationServiceRefusalError("no such dataset"), 422),
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


@pytest.mark.parametrize(
    ("path", "schema", "id_field"),
    [
        ("/v2/reports", "CreatedReportUnreadableResponse", "report_id"),
        ("/v2/simulations", "CreatedSimulationUnreadableResponse", "simulation_id"),
    ],
    ids=["report", "simulation"],
)
def test_the_openapi_document_gives_the_created_records_id_with_a_502(
    path: str, schema: str, id_field: str
) -> None:
    document = report_route_client().get("/v2/openapi.json").json()

    answer = document["paths"][path]["post"]["responses"]["502"]
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
