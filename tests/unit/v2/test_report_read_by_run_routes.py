"""The query contract of reading a v2 report by run, over a stand-in service."""

from __future__ import annotations

from uuid import uuid4

import pytest

from policyengine_api.services.v2.stored_reports.validators import (
    ReportRunNotFoundError,
)
from tests.unit.v2.stored_report_support import (
    REPORT_ID,
    REPORT_RUN_ID,
    FakeReportService,
    report_route_client,
)


def test_the_run_named_is_passed_to_the_service() -> None:
    service = FakeReportService()

    response = report_route_client(reports=service).get(
        f"/v2/reports/{REPORT_ID}?country_id=us&run_id={REPORT_RUN_ID}"
    )

    assert response.status_code == 200, response.text
    assert service.calls == [
        (
            "get_report",
            {"country_id": "us", "report_id": REPORT_ID, "run_id": REPORT_RUN_ID},
        )
    ]


def test_a_read_without_a_run_passes_none() -> None:
    service = FakeReportService()

    response = report_route_client(reports=service).get(
        f"/v2/reports/{REPORT_ID}?country_id=us"
    )

    assert response.status_code == 200, response.text
    assert service.calls[0][1]["run_id"] is None


@pytest.mark.parametrize(
    "query",
    [
        "country_id=us&run_id=not-a-uuid",
        f"country_id=us&run_id={uuid4()}&run_id={uuid4()}",
        f"country_id=us&run={uuid4()}",
    ],
    ids=["not-a-uuid", "repeated", "misspelled"],
)
def test_a_malformed_run_query_is_refused_before_the_service(query: str) -> None:
    service = FakeReportService()

    response = report_route_client(reports=service).get(
        f"/v2/reports/{REPORT_ID}?{query}"
    )

    assert response.status_code == 422, response.text
    assert service.calls == []


def test_a_run_the_report_does_not_have_answers_404() -> None:
    missing_run_id = uuid4()
    service = FakeReportService(
        error=ReportRunNotFoundError(f"Report {REPORT_ID} has no run {missing_run_id}")
    )

    response = report_route_client(reports=service).get(
        f"/v2/reports/{REPORT_ID}?country_id=us&run_id={missing_run_id}"
    )

    assert response.status_code == 404
    assert response.json() == {
        "status": "error",
        "message": f"Report {REPORT_ID} has no run {missing_run_id}",
    }


def test_openapi_declares_the_optional_run_query() -> None:
    document = report_route_client(reports=FakeReportService()).get("/v2/openapi.json")

    operation = document.json()["paths"]["/v2/reports/{report_id}"]["get"]
    run_parameter = next(
        parameter
        for parameter in operation["parameters"]
        if parameter["name"] == "run_id"
    )
    assert run_parameter["in"] == "query"
    assert run_parameter["required"] is False
    run_schemas = run_parameter["schema"]["anyOf"]
    assert {"type": "null"} in run_schemas
    assert any(
        schema.get("type") == "string" and schema.get("format") == "uuid"
        for schema in run_schemas
    )
