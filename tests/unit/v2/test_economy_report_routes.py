"""Route coverage for the native v2 economy reports.

The routes run on the real service, with SQLite countries rows and a fake
Simulation Entrypoint.
"""

from __future__ import annotations

import logging
import sys
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from flask import Flask, jsonify
from sqlalchemy.exc import OperationalError
from sqlmodel import select

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.models import Country
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    _default_economy_report_simulation,
    _default_v2_economy_report_service_factory,
)
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
    infer_route_group,
)
from policyengine_api.services.v2.economy_reports.types import EconomyReportFields
from policyengine_api.services.v2.economy_reports.validators import (
    EconomyReportsUnsupportedError,
)
from policyengine_api.services.v2.simulation_entrypoint.types import (
    ReportStatus,
    SimulationChoice,
    SimulationRecordUnreadableError,
    SimulationRequestRefusedError,
    SimulationServiceUnavailableError,
)
from tests.unit.v2.economy_report_support import (
    BASELINE_RUN_ID,
    BASELINE_SIMULATION_ID,
    CATALOG_VERSION_ID,
    CURRENT_POLICYENGINE_VERSION,
    HOUSEHOLD_ONLY_COUNTRY,
    REFORM_POLICY_ID,
    REFORM_RUN_ID,
    REFORM_SIMULATION_ID,
    REPORT_ID,
    REPORT_RUN_ID,
    RESULT,
    FakeEconomyReportSimulation,
    countries_store,
    economy_report_service,
    report_record,
    report_run_record,
)

SUBMISSION = {
    "country_id": "us",
    "kind": "economy",
    "year": 2026,
    "region_code": "state/ca",
    "baseline": {},
    "reform": {"policy_id": str(REFORM_POLICY_ID)},
}
CREATED_AT = "2026-10-27T12:00:00Z"


def _client(
    simulation: FakeEconomyReportSimulation,
    *,
    service_factory=None,
    sessions=None,
) -> TestClient:
    flask_app = Flask(__name__)

    @flask_app.route("/<path:resource>", methods=["GET", "POST"])
    def fallback(resource: str):
        return jsonify({"source": "flask", "resource": resource})

    service = economy_report_service(simulation, sessions)
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        specification_provider=dict,
        v2_economy_report_service_factory=service_factory or (lambda: service),
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    return TestClient(
        create_asgi_app(flask_app, dependencies=dependencies, route_settings=settings),
        raise_server_exceptions=False,
    )


def _simulation_item(simulation_id, policy_id=None) -> dict:
    return {
        "id": str(simulation_id),
        "kind": "economy",
        "country_id": "us",
        "policy_id": None if policy_id is None else str(policy_id),
        "dynamic_id": None,
        "region_code": "state/ca",
        "dataset_name": None,
        "legacy_simulation_id": None,
        "created_at": CREATED_AT,
    }


def _simulation_run_item(run_id, simulation_id) -> dict:
    return {
        "id": str(run_id),
        "simulation_id": str(simulation_id),
        "status": "pending",
        "attempt": 1,
        "trigger": "initial",
        "error": None,
        "dispatched_at": None,
        "completed_at": None,
        "created_at": CREATED_AT,
    }


PENDING_RUN_ITEM = {
    "id": str(REPORT_RUN_ID),
    "report_id": str(REPORT_ID),
    "trigger": "initial",
    "tax_benefit_model_version_id": str(CATALOG_VERSION_ID),
    "policyengine_version": CURRENT_POLICYENGINE_VERSION,
    "year": 2026,
    "status": "pending",
    "stage": "queued",
    "error": None,
    "baseline_run": _simulation_run_item(BASELINE_RUN_ID, BASELINE_SIMULATION_ID),
    "reform_run": _simulation_run_item(REFORM_RUN_ID, REFORM_SIMULATION_ID),
    "comparison": {
        "status": "pending",
        "error": None,
        "dispatched_at": None,
        "completed_at": None,
    },
    "created_at": CREATED_AT,
}


def test_submit_creates_the_report_and_answers_with_its_first_run() -> None:
    simulation = FakeEconomyReportSimulation()
    client = _client(simulation)

    response = client.post("/v2/reports?country_id=us", json=SUBMISSION)

    assert response.status_code == 201
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "item": {
                "id": str(REPORT_ID),
                "country_id": "us",
                "kind": "economy",
                "year": 2026,
                "options": {},
                "legacy_report_id": None,
                "created_at": CREATED_AT,
                "baseline_simulation": _simulation_item(BASELINE_SIMULATION_ID),
                "reform_simulation": _simulation_item(
                    REFORM_SIMULATION_ID, REFORM_POLICY_ID
                ),
                "status": "pending",
                "run": PENDING_RUN_ITEM,
                "result": None,
            }
        },
    }
    ((name, submission),) = simulation.calls
    assert name == "submit_report"
    assert submission.policyengine_version == CURRENT_POLICYENGINE_VERSION


def test_submit_needs_no_user_credential() -> None:
    client = _client(FakeEconomyReportSimulation())

    response = client.post(
        "/v2/reports?country_id=us", json=SUBMISSION, headers={"Authorization": ""}
    )

    assert response.status_code == 201


def test_submit_refuses_a_body_country_that_differs_from_the_query() -> None:
    simulation = FakeEconomyReportSimulation()
    client = _client(simulation)

    response = client.post("/v2/reports?country_id=uk", json=SUBMISSION)

    assert response.status_code == 400
    assert response.json() == {
        "status": "error",
        "message": "Body country_id must match query country_id",
    }
    assert simulation.calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "household"},
        {"kind": None},
        {"year": 1899},
        {"year": 2201},
        {"region_code": ""},
        {"region_code": "state ca"},
        {"dataset_name": ""},
        {"options": {}},
        {"baseline": {"policy_id": "not-a-uuid"}},
        {"reform": {"policy_id": str(REFORM_POLICY_ID), "extra": 1}},
        {"country_id": "ca"},
    ],
)
def test_submit_refuses_a_body_outside_the_contract(changes: dict) -> None:
    simulation = FakeEconomyReportSimulation()
    client = _client(simulation)

    response = client.post("/v2/reports?country_id=us", json={**SUBMISSION, **changes})

    assert response.status_code == 422
    assert response.json()["status"] == "error"
    assert simulation.calls == []


@pytest.mark.parametrize("missing", ["kind", "year", "region_code", "reform"])
def test_submit_refuses_a_body_missing_a_required_field(missing: str) -> None:
    simulation = FakeEconomyReportSimulation()
    body = {name: value for name, value in SUBMISSION.items() if name != missing}

    response = _client(simulation).post("/v2/reports?country_id=us", json=body)

    assert response.status_code == 422
    assert simulation.calls == []


def test_submit_for_a_household_only_country_is_refused_naming_it() -> None:
    sessions = countries_store()
    with sessions() as session:
        united_states = session.exec(select(Country).where(Country.id == "us")).one()
        united_states.society_wide_enabled = False
        session.commit()
    simulation = FakeEconomyReportSimulation()
    client = _client(simulation, sessions=sessions)

    response = client.post("/v2/reports?country_id=us", json=SUBMISSION)

    assert response.status_code == 422
    assert response.json() == {
        "status": "error",
        "message": "Economy reports are not available for country 'us'",
    }
    assert simulation.calls == []


def test_submit_relays_the_entrypoint_reason_when_it_cannot_run_the_report() -> None:
    simulation = FakeEconomyReportSimulation()
    reason = (
        "region place/ca-los_angeles has no household filter in this catalog version"
    )
    simulation.error = SimulationRequestRefusedError(reason)

    response = _client(simulation).post("/v2/reports?country_id=us", json=SUBMISSION)

    assert response.status_code == 422
    assert response.json() == {"status": "error", "message": reason}


@pytest.mark.parametrize(
    "error",
    [
        SimulationServiceUnavailableError("the entrypoint answered HTTP 503"),
        V2ConfigurationError("V2_RUNTIME_DATABASE_URL is not configured"),
        OperationalError("SELECT 1", {}, Exception("connection refused")),
    ],
    ids=["entrypoint", "configuration", "database"],
)
def test_submit_is_unavailable_when_a_dependency_is(error: Exception) -> None:
    def failing_service():
        raise error

    response = _client(
        FakeEconomyReportSimulation(), service_factory=failing_service
    ).post("/v2/reports?country_id=us", json=SUBMISSION)

    assert response.status_code == 503
    assert response.json()["status"] == "error"
    assert "connection refused" not in response.json()["message"]


def test_an_unexpected_failure_is_a_secret_safe_server_error() -> None:
    simulation = FakeEconomyReportSimulation()
    simulation.error = RuntimeError("token=secret")

    response = _client(simulation).post("/v2/reports?country_id=us", json=SUBMISSION)

    assert response.status_code == 500
    assert response.json() == {
        "status": "error",
        "message": "V2 report operation failed",
    }


def test_reports_are_unavailable_without_the_generated_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(
        sys.modules, "policyengine_api.libs.simulation_economy_reports", raising=False
    )
    monkeypatch.setitem(sys.modules, "policyengine_api_simulation_client", None)

    with pytest.raises(SimulationServiceUnavailableError) as raised:
        _default_economy_report_simulation()

    assert "policyengine-api-simulation-client" in str(raised.value)


def test_report_requests_are_logged_with_the_report_route_group() -> None:
    assert infer_route_group("/v2/reports") == "report"
    assert infer_route_group(f"/v2/reports/{REPORT_ID}/runs") == "report"


def test_openapi_publishes_the_submit_contract() -> None:
    schema = _client(FakeEconomyReportSimulation()).get("/v2/openapi.json").json()

    operation = schema["paths"]["/v2/reports"]["post"]
    assert {parameter["name"] for parameter in operation["parameters"]} == {
        "country_id"
    }
    assert set(operation["responses"]) >= {"201", "400", "422", "503"}
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/EconomyReportCreateRequest")
    body = schema["components"]["schemas"]["EconomyReportCreateRequest"]
    assert set(body["required"]) == {
        "country_id",
        "kind",
        "year",
        "region_code",
        "baseline",
        "reform",
    }
    assert body["additionalProperties"] is False


def test_a_succeeded_report_is_read_with_its_result() -> None:
    simulation = FakeEconomyReportSimulation(
        report_record(run=report_run_record(status=ReportStatus.SUCCEEDED))
    )

    response = _client(simulation).get(f"/v2/reports/{REPORT_ID}?country_id=us")

    assert response.status_code == 200
    item = response.json()["result"]["item"]
    assert item["status"] == "succeeded"
    assert item["run"]["status"] == "succeeded"
    assert item["result"] == RESULT


def test_reading_a_migrated_report_starts_its_first_run() -> None:
    simulation = FakeEconomyReportSimulation(report_record(legacy_report_id=615))

    response = _client(simulation).get(f"/v2/reports/{REPORT_ID}?country_id=us")

    assert response.status_code == 200
    item = response.json()["result"]["item"]
    assert item["legacy_report_id"] == 615
    assert item["status"] == "pending"
    assert item["run"]["trigger"] == "system"
    assert item["result"] is None


@pytest.mark.parametrize(
    "reports",
    [(), (report_record(country_id="uk"),)],
    ids=["unknown", "other-country"],
)
def test_a_report_outside_the_country_is_not_found(reports) -> None:
    response = _client(FakeEconomyReportSimulation(*reports)).get(
        f"/v2/reports/{REPORT_ID}?country_id=us"
    )

    assert response.status_code == 404
    assert response.json() == {
        "status": "error",
        "message": f"Economy report {REPORT_ID} was not found in country 'us'",
    }


@pytest.mark.parametrize(
    "path",
    [
        "/v2/reports/not-a-uuid?country_id=us",
        f"/v2/reports/{REPORT_ID}",
        f"/v2/reports/{REPORT_ID}?country_id=us&country_id=uk",
        f"/v2/reports/{REPORT_ID}?country_id=us&extra=1",
        "/v2/reports/by-legacy-number/0?country_id=us",
        "/v2/reports/by-legacy-number/first?country_id=us",
        "/v2/reports/by-legacy-number/615",
    ],
)
def test_a_read_outside_the_contract_is_refused(path: str) -> None:
    simulation = FakeEconomyReportSimulation(report_record(legacy_report_id=615))

    response = _client(simulation).get(path)

    assert response.status_code == 422
    assert simulation.calls == []


def test_a_migrated_report_is_found_by_its_v1_number() -> None:
    simulation = FakeEconomyReportSimulation(report_record(legacy_report_id=615))

    response = _client(simulation).get("/v2/reports/by-legacy-number/615?country_id=us")

    assert response.status_code == 200
    assert response.json()["result"]["item"]["id"] == str(REPORT_ID)
    assert simulation.calls[0] == ("get_report_by_legacy_id", 615)


def test_an_unknown_v1_number_is_not_found() -> None:
    response = _client(FakeEconomyReportSimulation()).get(
        "/v2/reports/by-legacy-number/615?country_id=us"
    )

    assert response.status_code == 404
    assert response.json()["message"] == (
        "Economy report migrated from v1 report 615 was not found in country 'us'"
    )


def test_openapi_publishes_the_read_contracts() -> None:
    schema = _client(FakeEconomyReportSimulation()).get("/v2/openapi.json").json()

    for path in (
        "/v2/reports/{report_id}",
        "/v2/reports/by-legacy-number/{legacy_report_id}",
    ):
        operation = schema["paths"][path]["get"]
        assert {parameter["name"] for parameter in operation["parameters"]} >= {
            "country_id"
        }
        assert set(operation["responses"]) >= {"200", "404", "422", "503"}
    legacy_number = next(
        parameter
        for parameter in schema["paths"][
            "/v2/reports/by-legacy-number/{legacy_report_id}"
        ]["get"]["parameters"]
        if parameter["name"] == "legacy_report_id"
    )
    assert legacy_number["schema"]["minimum"] == 1


def test_a_rerun_answers_with_the_new_run() -> None:
    simulation = FakeEconomyReportSimulation(report_record(run=report_run_record()))

    response = _client(simulation).post(
        f"/v2/reports/{REPORT_ID}/runs?country_id=us", json={"force": True}
    )

    assert response.status_code == 201
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {"item": {**PENDING_RUN_ITEM, "trigger": "manual"}},
    }
    assert simulation.calls[-1][1]["force"] is True


def test_a_rerun_reuses_simulation_runs_unless_forced() -> None:
    simulation = FakeEconomyReportSimulation(report_record(run=report_run_record()))

    response = _client(simulation).post(
        f"/v2/reports/{REPORT_ID}/runs?country_id=us", json={}
    )

    assert response.status_code == 201
    assert simulation.calls[-1][1]["force"] is False


def test_a_rerun_in_a_household_only_country_is_refused_naming_it() -> None:
    sessions = countries_store()
    with sessions() as session:
        united_states = session.exec(select(Country).where(Country.id == "us")).one()
        united_states.society_wide_enabled = False
        session.commit()
    simulation = FakeEconomyReportSimulation(report_record(run=report_run_record()))

    response = _client(simulation, sessions=sessions).post(
        f"/v2/reports/{REPORT_ID}/runs?country_id=us", json={}
    )

    assert response.status_code == 422
    assert response.json()["message"] == (
        "Economy reports are not available for country 'us'"
    )
    assert simulation.calls == []


@pytest.mark.parametrize(
    "body",
    [{"force": "yes"}, {"force": None}, {"trigger": "system"}, None],
    ids=["text", "null", "trigger", "no-body"],
)
def test_a_rerun_body_outside_the_contract_is_refused(body) -> None:
    simulation = FakeEconomyReportSimulation(report_record(run=report_run_record()))

    response = _client(simulation).post(
        f"/v2/reports/{REPORT_ID}/runs?country_id=us", json=body
    )

    assert response.status_code == 422
    assert simulation.calls == []


def test_a_reports_runs_are_listed() -> None:
    simulation = FakeEconomyReportSimulation(report_record())
    client = _client(simulation)
    client.get(f"/v2/reports/{REPORT_ID}?country_id=us")
    client.post(f"/v2/reports/{REPORT_ID}/runs?country_id=us", json={})

    response = client.get(f"/v2/reports/{REPORT_ID}/runs?country_id=us")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "items": [
                {**PENDING_RUN_ITEM, "trigger": "manual"},
                {**PENDING_RUN_ITEM, "trigger": "system"},
            ]
        },
    }


def test_the_runs_of_an_unknown_report_are_not_found() -> None:
    response = _client(FakeEconomyReportSimulation()).get(
        f"/v2/reports/{REPORT_ID}/runs?country_id=us"
    )

    assert response.status_code == 404


def test_openapi_publishes_the_run_contracts() -> None:
    schema = _client(FakeEconomyReportSimulation()).get("/v2/openapi.json").json()

    runs = schema["paths"]["/v2/reports/{report_id}/runs"]
    assert set(runs) == {"get", "post"}
    assert "201" in runs["post"]["responses"]
    assert set(runs["get"]["responses"]) >= {"200", "404", "422", "503"}
    body = schema["components"]["schemas"]["EconomyReportRunRequest"]
    assert body["additionalProperties"] is False
    assert body["properties"]["force"]["default"] is False


SECOND_REPORT_ID = "00000000-0000-4000-8000-000000000201"


def test_reports_are_listed_by_id_without_their_results() -> None:
    simulation = FakeEconomyReportSimulation(
        report_record(run=report_run_record(status=ReportStatus.SUCCEEDED)),
        report_record(report_id=UUID(SECOND_REPORT_ID), legacy_report_id=615),
    )

    response = _client(simulation).get(
        f"/v2/reports?country_id=us&report_id={SECOND_REPORT_ID}&report_id={REPORT_ID}"
    )

    assert response.status_code == 200
    items = response.json()["result"]["items"]
    assert [item["id"] for item in items] == [SECOND_REPORT_ID, str(REPORT_ID)]
    assert [item["status"] for item in items] == ["not_run", "succeeded"]
    assert all("result" not in item for item in items)
    assert items[0]["run"] is None
    assert [name for name, _ in simulation.calls] == ["get_report", "get_report"]


@pytest.mark.parametrize(
    "query",
    [
        "country_id=us",
        "country_id=us&report_id=not-a-uuid",
        "report_id=" + SECOND_REPORT_ID,
        "country_id=us&country_id=uk&report_id=" + SECOND_REPORT_ID,
        "country_id=us&"
        + "&".join(
            f"report_id=00000000-0000-4000-8000-{number:012d}" for number in range(26)
        ),
    ],
    ids=["no-ids", "bad-id", "no-country", "two-countries", "too-many"],
)
def test_a_listing_outside_the_contract_is_refused(query: str) -> None:
    simulation = FakeEconomyReportSimulation()

    response = _client(simulation).get(f"/v2/reports?{query}")

    assert response.status_code == 422
    assert simulation.calls == []


def test_openapi_publishes_the_listing_contract() -> None:
    schema = _client(FakeEconomyReportSimulation()).get("/v2/openapi.json").json()

    operation = schema["paths"]["/v2/reports"]["get"]
    report_ids = next(
        parameter
        for parameter in operation["parameters"]
        if parameter["name"] == "report_id"
    )
    assert report_ids["required"] is True
    assert report_ids["schema"]["type"] == "array"
    assert report_ids["schema"]["maxItems"] == 25
    item = schema["components"]["schemas"]["ReportSummaryItem"]
    assert "result" not in item["properties"]


def _without_the_generated_client(monkeypatch: pytest.MonkeyPatch, sessions) -> None:
    """Make the default factory's client import fail, and read countries from SQLite."""
    from policyengine_api.data.v2 import database

    monkeypatch.delitem(
        sys.modules, "policyengine_api.libs.simulation_economy_reports", raising=False
    )
    monkeypatch.setitem(sys.modules, "policyengine_api_simulation_client", None)
    monkeypatch.setattr(database, "get_v2_session_factory", lambda: sessions)


def test_the_default_service_refuses_a_household_only_country_without_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _without_the_generated_client(monkeypatch, countries_store(HOUSEHOLD_ONLY_COUNTRY))
    service = _default_v2_economy_report_service_factory()
    report_input = EconomyReportFields(
        kind="economy",
        year=2026,
        region_code="state/ca",
        baseline=SimulationChoice(),
        reform=SimulationChoice(),
    )

    with pytest.raises(EconomyReportsUnsupportedError):
        service.submit_report(country_id="zz", report_input=report_input)
    with pytest.raises(EconomyReportsUnsupportedError):
        service.run_report(country_id="zz", report_id=REPORT_ID, force=False)
    with pytest.raises(SimulationServiceUnavailableError):
        service.submit_report(country_id="us", report_input=report_input)


def test_a_household_only_submission_is_a_422_even_without_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = countries_store()
    with sessions() as session:
        united_states = session.exec(select(Country).where(Country.id == "us")).one()
        united_states.society_wide_enabled = False
        session.commit()
    _without_the_generated_client(monkeypatch, sessions)

    response = _client(
        FakeEconomyReportSimulation(),
        service_factory=_default_v2_economy_report_service_factory,
    ).post("/v2/reports?country_id=us", json=SUBMISSION)

    assert response.status_code == 422
    assert response.json()["message"] == (
        "Economy reports are not available for country 'us'"
    )


def test_a_report_whose_result_cannot_be_read_back_is_a_bad_gateway() -> None:
    simulation = FakeEconomyReportSimulation(report_record(run=report_run_record()))
    simulation.error = SimulationRecordUnreadableError(
        "The report's stored result cannot be read back."
    )

    response = _client(simulation).get(f"/v2/reports/{REPORT_ID}?country_id=us")

    assert response.status_code == 502
    assert response.json() == {
        "status": "error",
        "message": "The simulation service cannot read back this report's result",
    }


@pytest.mark.parametrize(
    ("method", "path", "statuses"),
    [
        ("post", "/v2/reports", {"201", "400", "413", "422", "500", "503"}),
        ("get", "/v2/reports", {"200", "422", "500", "503"}),
        (
            "get",
            "/v2/reports/{report_id}",
            {"200", "404", "422", "500", "502", "503"},
        ),
        (
            "get",
            "/v2/reports/by-legacy-number/{legacy_report_id}",
            {"200", "404", "422", "500", "502", "503"},
        ),
        (
            "post",
            "/v2/reports/{report_id}/runs",
            {"201", "404", "413", "422", "500", "503"},
        ),
        ("get", "/v2/reports/{report_id}/runs", {"200", "404", "422", "500", "503"}),
    ],
)
def test_openapi_declares_only_the_answers_each_route_can_give(
    method: str, path: str, statuses: set[str]
) -> None:
    schema = _client(FakeEconomyReportSimulation()).get("/v2/openapi.json").json()

    assert set(schema["paths"][path][method]["responses"]) == statuses


class RecordingHandler(logging.Handler):
    """Keep every record logged to the logger it is attached to."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_an_unexpected_failure_is_logged_with_where_it_happened() -> None:
    simulation = FakeEconomyReportSimulation()
    simulation.error = RuntimeError("token=secret")
    routes_logger = logging.getLogger(
        "policyengine_api.fastapi_routes.v2.reports.routes"
    )
    handler = RecordingHandler()
    # Alembic's logging configuration, run by earlier tests, disables loggers
    # that already exist.
    was_disabled = routes_logger.disabled
    routes_logger.disabled = False
    routes_logger.addHandler(handler)
    try:
        _client(simulation).post("/v2/reports?country_id=us", json=SUBMISSION)
    finally:
        routes_logger.removeHandler(handler)
        routes_logger.disabled = was_disabled

    (record,) = [
        record
        for record in handler.records
        if record.getMessage() == "v2_report_operation_failed"
    ]
    attributes = record.policyengine_attributes
    assert record.levelno == logging.ERROR
    assert attributes["error_type"] == "RuntimeError"
    assert "economy_report_support.py" in attributes["error_frames"]
    assert "secret" not in str(attributes)


@pytest.mark.parametrize(
    ("method", "path", "refuses_runs"),
    [
        ("post", "/v2/reports", True),
        ("post", "/v2/reports/{report_id}/runs", True),
        ("get", "/v2/reports", False),
        ("get", "/v2/reports/{report_id}", False),
        ("get", "/v2/reports/by-legacy-number/{legacy_report_id}", False),
        ("get", "/v2/reports/{report_id}/runs", False),
    ],
)
def test_openapi_says_which_routes_refuse_a_report_that_cannot_run(
    method: str, path: str, *, refuses_runs: bool
) -> None:
    schema = _client(FakeEconomyReportSimulation()).get("/v2/openapi.json").json()

    description = schema["paths"][path][method]["responses"]["422"]["description"]

    assert ("economy reports" in description) is refuses_runs
