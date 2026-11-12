"""Create v2 budget-window reports over stand-in services.

``POST /v2/reports`` takes a budget window as ``kind`` ``budget_window``,
beside economy reports. Its answers are an economy report's, with the
budget-window item.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from policyengine_api.services.v2.simulation_service.types import (
    BudgetWindowReportCreationInput,
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.stored_reports.validators import (
    CreatedReportUnreadableError,
)
from tests.unit.v2.budget_window_report_support import (
    BUDGET_WINDOW_REPORT_ID,
    budget_window_report_read,
)
from tests.unit.v2.stored_report_support import (
    POLICY_ID,
    FakeReportService,
    report_route_client,
)


def window_body(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "country_id": "us",
        "kind": "budget_window",
        "label": "Expanded child tax credit, ten years",
        "year": 2026,
        "budget_window_size": 10,
        "region_code": "us",
        "baseline": {},
        "reform": {"policy_id": str(POLICY_ID)},
    }
    return {**values, **changes}


def window_service() -> FakeReportService:
    return FakeReportService(
        report=budget_window_report_read(status="pending", result=None)
    )


def test_a_budget_window_is_created_and_answered_as_stored() -> None:
    service = window_service()

    response = report_route_client(reports=service).post(
        "/v2/reports?country_id=us",
        json=window_body(spm={"geography_kind": "national"}),
    )

    assert response.status_code == 201, response.text
    item = response.json()["result"]["item"]
    assert (item["id"], item["kind"]) == (str(BUDGET_WINDOW_REPORT_ID), "budget_window")
    assert [year["year"] for year in item["run"]["years"]] == [2026, 2027]
    ((operation, arguments),) = service.calls
    assert operation == "create_report"
    created = arguments["report_input"]
    assert isinstance(created, BudgetWindowReportCreationInput)
    assert (created.year, created.budget_window_size) == (2026, 10)
    assert created.reform.policy_id == POLICY_ID
    assert created.spm.geography_kind == "national"


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"budget_window_size": 0}, id="no-years"),
        pytest.param({"budget_window_size": 76}, id="over-75-years"),
        pytest.param({"year": 2195, "budget_window_size": 7}, id="ends-after-2200"),
        pytest.param({"budget_window_size": None}, id="null-size"),
        pytest.param({"include_cliffs": False}, id="cliffs"),
        pytest.param({"spm": None}, id="null-spm"),
        pytest.param({"kind": "household"}, id="unknown-kind"),
    ],
)
def test_a_budget_window_the_tables_cannot_hold_is_refused(
    changes: dict[str, Any],
) -> None:
    service = window_service()

    response = report_route_client(reports=service).post(
        "/v2/reports?country_id=us", json=window_body(**changes)
    )

    assert response.status_code == 422, response.text
    assert service.calls == []


def test_a_budget_window_needs_its_size() -> None:
    body = window_body()
    del body["budget_window_size"]
    service = window_service()

    response = report_route_client(reports=service).post(
        "/v2/reports?country_id=us", json=body
    )

    assert response.status_code == 422
    assert service.calls == []


def test_a_budget_window_body_naming_another_country_is_refused() -> None:
    service = window_service()

    response = report_route_client(reports=service).post(
        "/v2/reports?country_id=uk", json=window_body()
    )

    assert response.status_code == 400
    assert service.calls == []


def test_a_budget_window_the_service_failed_answers_503_with_its_id() -> None:
    report_id = uuid4()
    service = FakeReportService(
        error=SimulationServiceUnavailableError(
            f"The simulation service created report {report_id}, but is "
            "unavailable (503 modal_call_refused).",
            created_record_id=report_id,
        )
    )

    response = report_route_client(reports=service).post(
        "/v2/reports?country_id=us", json=window_body()
    )

    assert response.status_code == 503
    assert response.json()["report_id"] == str(report_id)


def test_a_created_budget_window_that_cannot_be_read_back_answers_502() -> None:
    report_id = uuid4()
    service = FakeReportService(
        error=CreatedReportUnreadableError(report_id=report_id, country_id="us")
    )

    response = report_route_client(reports=service).post(
        "/v2/reports?country_id=us", json=window_body()
    )

    assert response.status_code == 502
    assert response.json()["report_id"] == str(report_id)


def test_the_openapi_document_tells_the_report_bodies_apart_by_kind() -> None:
    document = report_route_client().get("/v2/openapi.json").json()

    body = document["paths"]["/v2/reports"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert body["discriminator"]["propertyName"] == "kind"
    assert set(body["discriminator"]["mapping"]) == {"economy", "budget_window"}
    window = document["components"]["schemas"]["BudgetWindowReportCreateRequest"]
    assert {"year", "budget_window_size"} <= set(window["required"])
    assert "include_cliffs" not in window["properties"]
    assert window["properties"]["year"]["description"] == "The window's first year"
