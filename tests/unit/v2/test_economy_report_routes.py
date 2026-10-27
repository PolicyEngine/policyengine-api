"""Route coverage for the native v2 economy reports.

The routes run on the real service, with SQLite countries rows and a fake
Simulation Entrypoint.
"""

from __future__ import annotations

import sys

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
)
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
    infer_route_group,
)
from policyengine_api.services.v2.economy_reports.types import (
    SimulationRequestRefusedError,
    SimulationServiceUnavailableError,
)
from tests.unit.v2.economy_report_support import (
    BASELINE_RUN_ID,
    BASELINE_SIMULATION_ID,
    CATALOG_VERSION_ID,
    CURRENT_POLICYENGINE_VERSION,
    REFORM_POLICY_ID,
    REFORM_RUN_ID,
    REFORM_SIMULATION_ID,
    REPORT_ID,
    REPORT_RUN_ID,
    FakeEconomyReportSimulation,
    countries_store,
    economy_report_service,
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
    assert set(operation["responses"]) >= {"201", "400", "404", "422", "503"}
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
