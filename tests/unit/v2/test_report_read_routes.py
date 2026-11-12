"""Read v2 reports and simulations over stand-in services."""

from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

import pytest

from policyengine_api.services.v2.stored_reports.economy_results.types import (
    EconomyResultUnreadableError,
)
from policyengine_api.services.v2.stored_reports.validators import (
    ReportKindUnsupportedError,
    ReportStorageError,
    StoredReportNotFoundError,
)
from policyengine_api.services.v2.stored_simulations.validators import (
    SimulationStorageError,
    StoredSimulationNotFoundError,
)
from tests.fixtures.economy_results import us_economy_result
from tests.unit.v2.stored_report_support import (
    REPORT_ID,
    FakeReportService,
    FakeSimulationService,
    report_route_client,
    report_summary_read,
)


def test_a_report_answers_its_definition_newest_run_versions_and_result() -> None:
    service = FakeReportService()
    client = report_route_client(reports=service)

    response = client.get(f"/v2/reports/{REPORT_ID}?country_id=us")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["message"] is None
    item = body["result"]["item"]
    assert item["result"] == json.loads(json.dumps(us_economy_result()))
    assert item["run"]["country_package_version"] == "1.4.0"
    assert item["run"]["policyengine_version"] == "4.1.0"
    assert item["current_versions"] == {
        "country_package_version": "1.5.0",
        "policyengine_version": "4.2.0",
    }
    assert item["reform_simulation"]["policy_id"] is not None
    assert service.calls == [
        ("get_report", {"country_id": "us", "report_id": REPORT_ID})
    ]


def test_a_reports_spm_receipts_are_answered_with_package_names_as_keys() -> None:
    client = report_route_client(reports=FakeReportService())

    item = client.get(f"/v2/reports/{REPORT_ID}?country_id=us").json()["result"]["item"]

    receipts = item["result"]["spm_provenance"]
    assert receipts == json.loads(json.dumps(us_economy_result()["spm_provenance"]))
    assert set(receipts["baseline"]["receipt"]["runtime_versions"]) == {
        "policyengine",
        "policyengine-core",
        "policyengine-us",
        "spm-calculator",
    }


def test_a_report_without_a_run_answers_with_no_run_and_no_result() -> None:
    service = FakeReportService()
    service.report = replace(service.report, status="not_run", run=None, result=None)

    item = (
        report_route_client(reports=service)
        .get(f"/v2/reports/{REPORT_ID}?country_id=us")
        .json()["result"]["item"]
    )

    assert item["status"] == "not_run"
    assert item["run"] is None
    assert item["result"] is None


@pytest.mark.parametrize(
    ("error", "status_code", "message"),
    [
        (
            StoredReportNotFoundError("Report x was not found in country 'us'"),
            404,
            "Report x was not found in country 'us'",
        ),
        (
            ReportKindUnsupportedError("Report x is a budget window"),
            422,
            "Report x is a budget window",
        ),
        (
            EconomyResultUnreadableError("the budget summary has no household_tax row"),
            500,
            "The report's stored result cannot be read",
        ),
        (
            ReportStorageError("V2 report storage is unavailable"),
            503,
            "V2 report storage is unavailable",
        ),
        (RuntimeError("unexpected"), 500, "V2 report operation failed"),
    ],
    ids=["not-found", "other-kind", "unreadable-result", "storage", "unexpected"],
)
def test_report_read_failures_answer_typed_errors(
    error: Exception, status_code: int, message: str
) -> None:
    client = report_route_client(reports=FakeReportService(error=error))

    response = client.get(f"/v2/reports/{REPORT_ID}?country_id=us")

    assert response.status_code == status_code
    assert response.json() == {"status": "error", "message": message}


def test_a_report_read_needs_a_country() -> None:
    response = report_route_client(reports=FakeReportService()).get(
        f"/v2/reports/{REPORT_ID}"
    )

    assert response.status_code == 422


def test_listing_passes_the_named_reports_in_order_and_answers_without_results() -> (
    None
):
    first, second = uuid4(), uuid4()
    service = FakeReportService(
        listed=(report_summary_read(id=second), report_summary_read(id=first))
    )
    client = report_route_client(reports=service)

    response = client.get(
        f"/v2/reports?country_id=us&report_id={second}&report_id={first}"
    )

    assert response.status_code == 200
    items = response.json()["result"]["items"]
    assert [item["id"] for item in items] == [str(second), str(first)]
    assert all("result" not in item for item in items)
    assert service.calls == [
        ("list_reports", {"country_id": "us", "report_ids": [second, first]})
    ]


@pytest.mark.parametrize(
    "query",
    [
        "country_id=us",
        "country_id=us&" + "&".join(f"report_id={uuid4()}" for _ in range(26)),
        f"country_id=us&report_id={uuid4()}&unknown=1",
        "country_id=us&report_id=not-a-uuid",
    ],
    ids=["no-report", "more-than-25", "unknown-parameter", "malformed-id"],
)
def test_listing_refuses_a_malformed_query(query: str) -> None:
    service = FakeReportService()

    response = report_route_client(reports=service).get(f"/v2/reports?{query}")

    assert response.status_code == 422
    assert service.calls == []


def test_listing_twenty_five_reports_is_allowed() -> None:
    service = FakeReportService()
    query = "&".join(f"report_id={uuid4()}" for _ in range(25))

    response = report_route_client(reports=service).get(
        f"/v2/reports?country_id=uk&{query}"
    )

    assert response.status_code == 200
    assert len(service.calls[0][1]["report_ids"]) == 25


def test_a_simulation_answers_its_definition_newest_run_and_versions() -> None:
    service = FakeSimulationService()
    simulation_id = service.simulation.id

    response = report_route_client(simulations=service).get(
        f"/v2/simulations/{simulation_id}?country_id=us"
    )

    assert response.status_code == 200
    item = response.json()["result"]["item"]
    assert item["id"] == str(simulation_id)
    assert item["kind"] == "economy"
    assert item["status"] == "pending"
    assert item["run"]["policyengine_version"] == "4.2.0"
    assert item["current_versions"]["country_package_version"] == "1.5.0"
    assert service.calls == [
        (
            "get_simulation",
            {"country_id": "us", "simulation_id": simulation_id},
        )
    ]


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (StoredSimulationNotFoundError("Simulation x was not found"), 404),
        (SimulationStorageError("V2 simulation storage is unavailable"), 503),
    ],
    ids=["not-found", "storage"],
)
def test_simulation_read_failures_answer_typed_errors(
    error: Exception, status_code: int
) -> None:
    client = report_route_client(simulations=FakeSimulationService(error=error))

    response = client.get(f"/v2/simulations/{uuid4()}?country_id=us")

    assert response.status_code == status_code
    assert response.json()["status"] == "error"
