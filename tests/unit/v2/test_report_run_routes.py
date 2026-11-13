"""Run v2 reports again and list their runs over stand-in services."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from policyengine_api.services.v2.household_calculations.validators import (
    HouseholdCalculationCountryError,
)
from policyengine_api.services.v2.policies.validators import (
    PolicyNotFoundError,
    PolicyParametersMissingError,
)
from policyengine_api.services.v2.simulation_service.types import (
    SimulationServiceAnswerUnreadableError,
    SimulationServiceConflictError,
    SimulationServiceInternalError,
    SimulationServiceInvalidRequestError,
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.simulation_service.validators import (
    EconomyCalculationsUnsupportedError,
    SubmissionStorageError,
)
from policyengine_api.services.v2.stored_reports.validators import (
    ReportStorageError,
    RerunReportUnreadableError,
    StoredReportNotFoundError,
)
from tests.unit.v2.budget_window_report_support import (
    BUDGET_WINDOW_REPORT_ID,
    budget_window_report_read,
)
from tests.unit.v2.report_run_support import (
    NEW_RUN_ID,
    NEW_WINDOW_RUN_ID,
    FakeReportRunService,
    budget_window_runs_read,
    report_runs_read,
)
from tests.unit.v2.stored_report_support import (
    BASELINE_RUN_ID,
    POLICY_ID,
    REPORT_ID,
    REPORT_RUN_ID,
    report_route_client,
    report_run_read,
)

RUNS_PATH = f"/v2/reports/{REPORT_ID}/runs?country_id=us"
RUNNING_RUN_ID = UUID("00000000-0000-0000-0000-00000000a00c")


def test_a_reports_runs_are_answered_newest_first_with_versions_and_current_ones() -> (
    None
):
    service = FakeReportRunService()

    response = report_route_client(reports=service).get(RUNS_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["message"] is None
    result = body["result"]
    assert result["report_id"] == str(REPORT_ID)
    assert result["kind"] == "economy"
    assert [run["id"] for run in result["items"]] == [
        str(NEW_RUN_ID),
        str(REPORT_RUN_ID),
    ]
    assert [run["trigger"] for run in result["items"]] == ["manual", "initial"]
    assert [
        (run["country_package_version"], run["policyengine_version"])
        for run in result["items"]
    ] == [("1.5.0", "4.2.0"), ("1.4.0", "4.1.0")]
    assert result["current_versions"] == {
        "country_package_version": "1.5.0",
        "policyengine_version": "4.2.0",
    }
    assert service.calls == [
        ("list_report_runs", {"country_id": "us", "report_id": REPORT_ID})
    ]


def test_a_household_reports_runs_are_answered_as_a_household_reports() -> None:
    service = FakeReportRunService(runs=replace(report_runs_read(), kind="household"))

    response = report_route_client(reports=service).get(RUNS_PATH)

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["kind"] == "household"
    assert [run["id"] for run in result["items"]] == [
        str(NEW_RUN_ID),
        str(REPORT_RUN_ID),
    ]
    assert result["current_versions"]["policyengine_version"] == "4.2.0"


def test_a_household_report_of_the_baseline_alone_lists_no_reform_run() -> None:
    baseline_alone = replace(
        report_runs_read(),
        kind="household",
        runs=(report_run_read(reform_simulation_run_id=None),),
    )
    service = FakeReportRunService(runs=baseline_alone)

    response = report_route_client(reports=service).get(RUNS_PATH)

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["kind"] == "household"
    (run,) = result["items"]
    assert run["id"] == str(REPORT_RUN_ID)
    assert run["baseline_simulation_run_id"] == str(BASELINE_RUN_ID)
    assert run["reform_simulation_run_id"] is None


def test_a_budget_windows_runs_are_answered_with_their_years() -> None:
    service = FakeReportRunService(runs=budget_window_runs_read())

    response = report_route_client(reports=service).get(
        f"/v2/reports/{BUDGET_WINDOW_REPORT_ID}/runs?country_id=us"
    )

    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["report_id"] == str(BUDGET_WINDOW_REPORT_ID)
    assert result["kind"] == "budget_window"
    newest, first = result["items"]
    assert newest["id"] == str(NEW_WINDOW_RUN_ID)
    assert (newest["trigger"], newest["recalculate"]) == ("manual", True)
    assert newest["policyengine_version"] == "4.2.0"
    assert [year["year"] for year in first["years"]] == [2026, 2027]
    assert first["years"][0]["country_package_version"] == "1.4.0"
    assert result["current_versions"]["policyengine_version"] == "4.2.0"


def test_running_a_budget_window_again_answers_the_window_with_its_new_run() -> None:
    window = budget_window_report_read(status="pending", result=None)
    service = FakeReportRunService(rerun=window)

    response = report_route_client(reports=service).post(
        f"/v2/reports/{BUDGET_WINDOW_REPORT_ID}/runs?country_id=us",
        json={"force": True},
    )

    assert response.status_code == 201, response.text
    item = response.json()["result"]["item"]
    assert item["kind"] == "budget_window"
    assert item["budget_window_size"] == 2
    assert [year["year"] for year in item["run"]["years"]] == [2026, 2027]
    assert item["result"] is None


def test_a_report_with_no_run_lists_none() -> None:
    service = FakeReportRunService()
    service.runs = replace(service.runs, runs=())

    response = report_route_client(reports=service).get(RUNS_PATH)

    assert response.status_code == 200
    assert response.json()["result"]["items"] == []


@pytest.mark.parametrize(
    ("error", "status_code", "message"),
    [
        (
            StoredReportNotFoundError("Report x was not found in country 'us'"),
            404,
            "Report x was not found in country 'us'",
        ),
        (
            ReportStorageError("V2 report storage is unavailable"),
            503,
            "V2 report storage is unavailable",
        ),
        (RuntimeError("unexpected"), 500, "V2 report operation failed"),
    ],
    ids=["not-found", "storage", "unexpected"],
)
def test_run_list_failures_answer_typed_errors(
    error: Exception, status_code: int, message: str
) -> None:
    client = report_route_client(reports=FakeReportRunService(error=error))

    response = client.get(RUNS_PATH)

    assert response.status_code == status_code
    assert response.json() == {"status": "error", "message": message}


@pytest.mark.parametrize(
    "query",
    ["", "?country_id=us&unknown=1", "?country_id=us&country_id=uk"],
    ids=["no-country", "unknown-parameter", "repeated-country"],
)
def test_a_run_list_refuses_a_malformed_query(query: str) -> None:
    service = FakeReportRunService()

    response = report_route_client(reports=service).get(
        f"/v2/reports/{REPORT_ID}/runs{query}"
    )

    assert response.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize(
    ("body", "force"),
    [({}, False), ({"force": False}, False), ({"force": True}, True)],
    ids=["empty", "reuse", "force"],
)
def test_running_a_report_again_answers_the_report_with_its_new_run(
    body: dict[str, bool],
    force: bool,  # noqa: FBT001  # pytest passes parameters positionally
) -> None:
    service = FakeReportRunService()
    service.report = replace(
        service.report,
        status="pending",
        run=report_run_read(id=NEW_RUN_ID, status="pending", trigger="manual"),
        result=None,
    )

    response = report_route_client(reports=service).post(RUNS_PATH, json=body)

    assert response.status_code == 201
    item = response.json()["result"]["item"]
    assert item["id"] == str(REPORT_ID)
    assert item["status"] == "pending"
    assert item["run"]["id"] == str(NEW_RUN_ID)
    assert item["run"]["trigger"] == "manual"
    assert item["result"] is None
    assert item["current_versions"]["policyengine_version"] == "4.2.0"
    assert service.calls == [
        ("rerun_report", {"country_id": "us", "report_id": REPORT_ID, "force": force})
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"force": "yes"},
        {"force": 1},
        {"force": None},
        {"force": True, "country_id": "us"},
        [],
        "force",
    ],
    ids=["text", "number", "null", "extra-field", "list", "string"],
)
def test_a_rerun_refuses_a_malformed_body(body: object) -> None:
    service = FakeReportRunService()

    response = report_route_client(reports=service).post(RUNS_PATH, json=body)

    assert response.status_code == 422
    assert service.calls == []


def test_a_rerun_needs_a_body() -> None:
    service = FakeReportRunService()

    response = report_route_client(reports=service).post(RUNS_PATH)

    assert response.status_code == 422
    assert service.calls == []


def test_a_rerun_needs_a_country() -> None:
    service = FakeReportRunService()

    response = report_route_client(reports=service).post(
        f"/v2/reports/{REPORT_ID}/runs", json={}
    )

    assert response.status_code == 422
    assert service.calls == []


def test_a_rerun_body_over_16_kib_is_refused() -> None:
    service = FakeReportRunService()

    response = report_route_client(reports=service).post(
        RUNS_PATH, json={"force": True, "padding": "x" * (17 * 1024)}
    )

    assert response.status_code == 413
    assert service.calls == []


@pytest.mark.parametrize(
    ("run_id", "answered_run_id"),
    [(RUNNING_RUN_ID, str(RUNNING_RUN_ID)), (None, None)],
    ids=["run-in-progress", "not-run-again"],
)
def test_a_report_the_service_will_not_run_again_now_answers_409(
    run_id: UUID | None, answered_run_id: str | None
) -> None:
    message = (
        "The simulation service will not run the report again now "
        "(run_in_progress): Report r has run x running."
    )
    service = FakeReportRunService(
        error=SimulationServiceConflictError(message, run_id=run_id)
    )

    response = report_route_client(reports=service).post(RUNS_PATH, json={})

    assert response.status_code == 409
    assert response.json() == {
        "status": "error",
        "message": message,
        "run_id": answered_run_id,
    }


def test_a_new_run_whose_report_cannot_be_read_back_answers_the_reports_id() -> None:
    service = FakeReportRunService(
        error=RerunReportUnreadableError(report_id=REPORT_ID, country_id="us")
    )

    response = report_route_client(reports=service).post(RUNS_PATH, json={})

    assert response.status_code == 502
    assert response.json() == {
        "status": "error",
        "message": (
            f"The simulation service started a new run of report {REPORT_ID}, "
            "but the report could not be read back. Read it with GET "
            f"/v2/reports/{REPORT_ID}?country_id=us rather than running it again."
        ),
        "report_id": str(REPORT_ID),
    }


@pytest.mark.parametrize(
    ("error", "status_code", "message"),
    [
        (
            StoredReportNotFoundError("Report x was not found in country 'us'"),
            404,
            "Report x was not found in country 'us'",
        ),
        (
            PolicyNotFoundError("Policy p was not found in country 'us'"),
            404,
            "Policy p was not found in country 'us'",
        ),
        (
            HouseholdCalculationCountryError(
                "Household calculations are not available for country us."
            ),
            422,
            "Household calculations are not available for country us.",
        ),
        (
            EconomyCalculationsUnsupportedError("No economy calculations for 'uk'"),
            422,
            "No economy calculations for 'uk'",
        ),
        (
            SimulationServiceInvalidRequestError(
                "The simulation service cannot run the report again "
                "(unknown_region): no region state/ca"
            ),
            422,
            "The simulation service cannot run the report again "
            "(unknown_region): no region state/ca",
        ),
        (
            SimulationServiceInternalError("may have started a new run"),
            502,
            "may have started a new run",
        ),
        (
            SimulationServiceAnswerUnreadableError("its answer was lost"),
            502,
            "its answer was lost",
        ),
        (
            SimulationServiceUnavailableError(
                "The simulation service is unavailable (503)."
            ),
            503,
            "The simulation service is unavailable (503).",
        ),
        (
            SubmissionStorageError("V2 storage is unavailable to check"),
            503,
            "V2 storage is unavailable",
        ),
        (
            ReportStorageError("V2 report storage is unavailable"),
            503,
            "V2 report storage is unavailable",
        ),
        (RuntimeError("unexpected"), 500, "V2 report operation failed"),
    ],
    ids=[
        "report-not-found",
        "policy-not-found",
        "no-household-calculations",
        "household-only-country",
        "service-refusal",
        "service-failure",
        "service-answer-lost",
        "service-unavailable",
        "check-storage",
        "report-storage",
        "unexpected",
    ],
)
def test_rerun_failures_answer_typed_errors(
    error: Exception, status_code: int, message: str
) -> None:
    client = report_route_client(reports=FakeReportRunService(error=error))

    response = client.post(RUNS_PATH, json={"force": True})

    assert response.status_code == status_code
    assert response.json() == {"status": "error", "message": message}


def test_a_rerun_of_a_policy_setting_missing_parameters_answers_422() -> None:
    error = PolicyParametersMissingError(POLICY_ID, ("gov.example.removed_amount",))
    client = report_route_client(reports=FakeReportRunService(error=error))

    response = client.post(RUNS_PATH, json={})

    assert response.status_code == 422
    assert response.json() == {
        "status": "error",
        "message": str(error),
        "code": "missing_parameters",
        "missing_parameters": ["gov.example.removed_amount"],
    }


def test_the_openapi_document_describes_both_run_routes() -> None:
    document = report_route_client().get("/v2/openapi.json").json()

    runs = document["paths"]["/v2/reports/{report_id}/runs"]
    assert set(runs) == {"get", "post"}
    assert {"200", "404", "422", "500", "503"} <= set(runs["get"]["responses"])
    assert {"201", "404", "409", "413", "422", "500", "502", "503"} <= set(
        runs["post"]["responses"]
    )
    conflict_schema = runs["post"]["responses"]["409"]["content"]["application/json"][
        "schema"
    ]
    assert conflict_schema == {
        "$ref": "#/components/schemas/ReportRerunConflictResponse"
    }
    assert {"$ref": "#/components/schemas/RerunReportUnreadableResponse"} in runs[
        "post"
    ]["responses"]["502"]["content"]["application/json"]["schema"]["anyOf"]
    assert {"$ref": "#/components/schemas/V2MissingParametersErrorResponse"} in runs[
        "post"
    ]["responses"]["422"]["content"]["application/json"]["schema"]["anyOf"]


def test_the_openapi_document_gives_each_kinds_run_list() -> None:
    document = report_route_client().get("/v2/openapi.json").json()

    schemas = document["components"]["schemas"]
    result = schemas["ReportRunListResponse"]["properties"]["result"]
    assert result["discriminator"]["propertyName"] == "kind"
    assert {option["$ref"] for option in result["oneOf"]} == {
        "#/components/schemas/ReportRunListResult",
        "#/components/schemas/BudgetWindowRunListResult",
    }
    assert result["discriminator"]["mapping"] == {
        "economy": "#/components/schemas/ReportRunListResult",
        "household": "#/components/schemas/ReportRunListResult",
        "budget_window": "#/components/schemas/BudgetWindowRunListResult",
    }
