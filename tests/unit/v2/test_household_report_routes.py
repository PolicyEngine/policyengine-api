"""Route coverage for household reports at the native v2 report routes.

The routes run on the real economy and household report services, with SQLite
countries and catalog rows, fake stored households and policies, and fake
Simulation Entrypoints.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from flask import Flask, jsonify

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.simulation_entrypoint.types import (
    ReportStatus,
    SimulationRequestRefusedError,
    SimulationServiceUnavailableError,
)
from tests.unit.v2.economy_report_support import (
    CURRENT_POLICYENGINE_VERSION,
    FakeEconomyReportSimulation,
    economy_report_service,
)
from tests.unit.v2.household_report_support import (
    BASELINE_CALCULATION_ID,
    CALCULATED_AT,
    CALCULATED_HOUSEHOLD,
    HOUSEHOLD_CATALOG_VERSION_ID,
    HOUSEHOLD_ID,
    HOUSEHOLD_REFORM_POLICY_ID,
    HOUSEHOLD_REPORT_ID,
    HOUSEHOLD_REPORT_RUN_ID,
    REFORM_CALCULATION_ID,
    FakeHouseholdReportSimulation,
    FakeHouseholds,
    household_report_record,
    household_report_service,
    household_report_store,
    household_simulation_ids,
    set_country_support,
    stored_household,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

SUBMISSION = {
    "country_id": "us",
    "kind": "household",
    "household_id": str(HOUSEHOLD_ID),
    "baseline": {},
    "reform": {"policy_id": str(HOUSEHOLD_REFORM_POLICY_ID)},
}
CALCULATED_AT_TEXT = CALCULATED_AT.isoformat().replace("+00:00", "Z")
BASELINE_SIMULATION_ID, REFORM_SIMULATION_ID = household_simulation_ids(
    HOUSEHOLD_REPORT_ID
)


def _client(
    simulation: FakeHouseholdReportSimulation,
    *,
    economy_simulation: FakeEconomyReportSimulation | None = None,
    households: FakeHouseholds | None = None,
    sessions: sessionmaker[Session] | None = None,
) -> TestClient:
    flask_app = Flask(__name__)

    @flask_app.route("/<path:resource>", methods=["GET", "POST"])
    def fallback(resource: str):
        return jsonify({"source": "flask", "resource": resource})

    sessions = household_report_store() if sessions is None else sessions
    economy_service = economy_report_service(
        economy_simulation or FakeEconomyReportSimulation(), sessions
    )
    household_service = household_report_service(
        simulation, households=households, sessions=sessions
    )
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        specification_provider=dict,
        v2_economy_report_service_factory=lambda: economy_service,
        v2_household_report_service_factory=lambda: household_service,
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


def _calculation_item(calculation_id: UUID, simulation_id: UUID, policy_id) -> dict:
    return {
        "id": str(calculation_id),
        "simulation_id": str(simulation_id),
        "policy_id": None if policy_id is None else str(policy_id),
        "status": "pending",
        "attempt": 1,
        "trigger": "initial",
        "error": None,
        "result": None,
        "dispatched_at": None,
        "completed_at": None,
        "created_at": CALCULATED_AT_TEXT,
    }


PENDING_REPORT_ITEM = {
    "id": str(HOUSEHOLD_REPORT_ID),
    "country_id": "us",
    "kind": "household",
    "year": 2026,
    "household_id": str(HOUSEHOLD_ID),
    "baseline_simulation_id": str(BASELINE_SIMULATION_ID),
    "reform_simulation_id": str(REFORM_SIMULATION_ID),
    "status": "pending",
    "run": {
        "kind": "household",
        "id": str(HOUSEHOLD_REPORT_RUN_ID),
        "report_id": str(HOUSEHOLD_REPORT_ID),
        "trigger": "initial",
        "tax_benefit_model_version_id": str(HOUSEHOLD_CATALOG_VERSION_ID),
        "policyengine_version": CURRENT_POLICYENGINE_VERSION,
        "year": 2026,
        "status": "pending",
        "baseline": _calculation_item(
            BASELINE_CALCULATION_ID, BASELINE_SIMULATION_ID, None
        ),
        "reform": _calculation_item(
            REFORM_CALCULATION_ID, REFORM_SIMULATION_ID, HOUSEHOLD_REFORM_POLICY_ID
        ),
    },
}


def test_a_household_report_is_submitted_and_answered_with_its_first_run() -> None:
    simulation = FakeHouseholdReportSimulation()

    response = _client(simulation).post("/v2/reports?country_id=us", json=SUBMISSION)

    assert response.status_code == 201, response.text
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {"item": PENDING_REPORT_ITEM},
    }
    assert [name for name, _argument in simulation.calls] == ["submit_report"]


def test_a_succeeded_household_report_carries_each_calculated_household() -> None:
    simulation = FakeHouseholdReportSimulation()
    simulation.next_status = ReportStatus.SUCCEEDED

    response = _client(simulation).post("/v2/reports?country_id=us", json=SUBMISSION)

    run = response.json()["result"]["item"]["run"]
    assert run["status"] == "succeeded"
    assert run["baseline"]["result"] == {
        "household": CALCULATED_HOUSEHOLD,
        "warnings": [],
        "spm_config": None,
        "spm_provenance": None,
    }
    assert run["reform"]["result"]["household"] == CALCULATED_HOUSEHOLD


def test_a_baseline_only_household_report_has_no_reform() -> None:
    simulation = FakeHouseholdReportSimulation()

    response = _client(simulation).post(
        "/v2/reports?country_id=us", json={**SUBMISSION, "reform": None}
    )

    assert response.status_code == 201, response.text
    item = response.json()["result"]["item"]
    assert item["reform_simulation_id"] is None
    assert item["run"]["reform"] is None


def test_an_economy_submission_still_reaches_the_economy_service() -> None:
    simulation = FakeHouseholdReportSimulation()
    economy_simulation = FakeEconomyReportSimulation()

    response = _client(simulation, economy_simulation=economy_simulation).post(
        "/v2/reports?country_id=us",
        json={
            "country_id": "us",
            "kind": "economy",
            "year": 2026,
            "region_code": "state/ca",
            "baseline": {},
            "reform": {},
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["result"]["item"]["kind"] == "economy"
    assert simulation.calls == []
    assert [name for name, _argument in economy_simulation.calls] == ["submit_report"]


def test_a_household_only_country_accepts_household_reports() -> None:
    sessions = household_report_store()
    set_country_support(
        sessions, "us", household_enabled=True, society_wide_enabled=False
    )
    simulation = FakeHouseholdReportSimulation()

    response = _client(simulation, sessions=sessions).post(
        "/v2/reports?country_id=us", json=SUBMISSION
    )

    assert response.status_code == 201, response.text
    assert [name for name, _argument in simulation.calls] == ["submit_report"]


def test_a_country_without_household_calculations_is_refused_with_422() -> None:
    sessions = household_report_store()
    set_country_support(
        sessions, "us", household_enabled=False, society_wide_enabled=False
    )
    simulation = FakeHouseholdReportSimulation()

    response = _client(simulation, sessions=sessions).post(
        "/v2/reports?country_id=us", json=SUBMISSION
    )

    assert response.status_code == 422, response.text
    assert response.json()["message"] == (
        "Household reports are not available for country 'us'"
    )
    assert simulation.calls == []


@pytest.mark.parametrize(
    ("changes", "households"),
    [
        ({"household_id": "00000000-0000-4000-8000-0000000003ff"}, None),
        ({"reform": {"policy_id": "00000000-0000-4000-8000-0000000003ff"}}, None),
        ({}, FakeHouseholds(stored_household(country_id="uk"))),
    ],
    ids=["unknown-household", "unknown-policy", "other-countrys-household"],
)
def test_a_household_or_policy_the_country_lacks_is_not_found(
    changes: dict, households: FakeHouseholds | None
) -> None:
    simulation = FakeHouseholdReportSimulation()

    response = _client(simulation, households=households).post(
        "/v2/reports?country_id=us", json={**SUBMISSION, **changes}
    )

    assert response.status_code == 404, response.text
    assert simulation.calls == []


def test_a_household_without_a_default_year_is_refused_with_422() -> None:
    simulation = FakeHouseholdReportSimulation()

    response = _client(
        simulation, households=FakeHouseholds(stored_household(default_year=None))
    ).post("/v2/reports?country_id=us", json=SUBMISSION)

    assert response.status_code == 422, response.text
    assert "default year" in response.json()["message"]
    assert simulation.calls == []


def test_the_entrypoint_refusal_of_the_callers_data_is_422_with_its_reason() -> None:
    simulation = FakeHouseholdReportSimulation()
    simulation.error = SimulationRequestRefusedError(
        "The policy changes gov.x, which the catalog version lacks."
    )

    response = _client(simulation).post("/v2/reports?country_id=us", json=SUBMISSION)

    assert response.status_code == 422, response.text
    assert response.json()["message"] == (
        "The policy changes gov.x, which the catalog version lacks."
    )


def test_an_unavailable_entrypoint_is_503() -> None:
    simulation = FakeHouseholdReportSimulation()
    simulation.error = SimulationServiceUnavailableError("it answered HTTP 400")

    response = _client(simulation).post("/v2/reports?country_id=us", json=SUBMISSION)

    assert response.status_code == 503, response.text
    assert response.json()["message"] == "The simulation service is unavailable"


@pytest.mark.parametrize(
    "changes",
    [
        {"year": 2026},
        {"options": {"axes": []}},
        {"baseline": {"dynamic_id": str(HOUSEHOLD_ID)}},
        {"household_id": "not-a-uuid"},
    ],
    ids=["year", "options", "dynamic", "household-id"],
)
def test_fields_outside_the_household_report_contract_are_refused(
    changes: dict,
) -> None:
    simulation = FakeHouseholdReportSimulation()

    response = _client(simulation).post(
        "/v2/reports?country_id=us", json={**SUBMISSION, **changes}
    )

    assert response.status_code == 422, response.text
    assert simulation.calls == []


def test_the_body_and_query_must_name_the_same_country() -> None:
    simulation = FakeHouseholdReportSimulation()

    response = _client(simulation).post("/v2/reports?country_id=uk", json=SUBMISSION)

    assert response.status_code == 400, response.text
    assert simulation.calls == []


def test_openapi_describes_both_kinds_of_report() -> None:
    schema = _client(FakeHouseholdReportSimulation()).get("/v2/openapi.json").json()

    body_schema = schema["paths"]["/v2/reports"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert body_schema["discriminator"]["propertyName"] == "kind"
    assert set(body_schema["discriminator"]["mapping"]) == {"economy", "household"}
    item_schema = schema["components"]["schemas"]["ReportDetailResult"]["properties"][
        "item"
    ]
    assert set(item_schema["discriminator"]["mapping"]) == {"economy", "household"}


def test_a_household_report_is_read_by_its_id() -> None:
    simulation = FakeHouseholdReportSimulation(household_report_record())

    response = _client(simulation).get(
        f"/v2/reports/{HOUSEHOLD_REPORT_ID}?country_id=us"
    )

    assert response.status_code == 200, response.text
    assert response.json()["result"]["item"] == PENDING_REPORT_ITEM


def test_a_report_of_neither_kind_is_404() -> None:
    response = _client(FakeHouseholdReportSimulation()).get(
        f"/v2/reports/{HOUSEHOLD_REPORT_ID}?country_id=us"
    )

    assert response.status_code == 404, response.text
    assert response.json()["message"] == (
        f"Report {HOUSEHOLD_REPORT_ID} was not found in country 'us'"
    )


def test_another_countrys_household_report_is_404() -> None:
    simulation = FakeHouseholdReportSimulation(household_report_record(country_id="uk"))

    response = _client(simulation).get(
        f"/v2/reports/{HOUSEHOLD_REPORT_ID}?country_id=us"
    )

    assert response.status_code == 404, response.text


def test_a_listing_summarizes_household_reports_without_their_calculations() -> None:
    simulation = FakeHouseholdReportSimulation(
        household_report_record(status=ReportStatus.SUCCEEDED)
    )

    response = _client(simulation).get(
        f"/v2/reports?country_id=us&report_id={HOUSEHOLD_REPORT_ID}"
    )

    assert response.status_code == 200, response.text
    (item,) = response.json()["result"]["items"]
    assert item["kind"] == "household"
    assert item["status"] == "succeeded"
    assert item["run"] == {
        "kind": "household",
        "id": str(HOUSEHOLD_REPORT_RUN_ID),
        "report_id": str(HOUSEHOLD_REPORT_ID),
        "trigger": "initial",
        "tax_benefit_model_version_id": str(HOUSEHOLD_CATALOG_VERSION_ID),
        "policyengine_version": CURRENT_POLICYENGINE_VERSION,
        "year": 2026,
        "status": "succeeded",
    }


def test_openapi_lists_both_kinds_of_report_summary() -> None:
    schema = _client(FakeHouseholdReportSimulation()).get("/v2/openapi.json").json()

    items_schema = schema["components"]["schemas"]["ReportListResult"]["properties"][
        "items"
    ]["items"]
    assert set(items_schema["discriminator"]["mapping"]) == {"economy", "household"}
