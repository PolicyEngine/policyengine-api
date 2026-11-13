"""Native FastAPI routes for v2 reports.

The routes need no user credential: a user keeps a report through
``/v2/user-reports``. Reports, their runs and results are read from the
detailed-save tables the simulation service and its Modal workers write;
reading never calls the simulation service and never starts a run. A report
is an economy report, a household report or a budget window, which its
``kind`` names. Creating a report checks it, has the simulation service
create and start it, and reads it back. Running a report again checks it as
a new report of its kind is checked, has the simulation service start its
new run, and reads the report back; listing its runs reads them, newest
first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse

from policyengine_api.fastapi_routes.dependencies import (
    _default_v2_stored_report_service_factory,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.errors_support import (
    V2ErrorMapping,
    v2_error_response,
)
from policyengine_api.fastapi_routes.v2.reports.request_models import (
    ReportCreateRequest,
)
from policyengine_api.fastapi_routes.v2.reports.response_models import (
    CREATE_RESPONSES,
    READ_RESPONSES,
    REPORT_ERROR_RESPONSES,
    CreatedReportUnreadableResponse,
    ReportDetailResponse,
    ReportDetailResult,
    ReportListResponse,
    ReportListResult,
    UnavailableAfterReportCreatedResponse,
    report_item,
    report_summary_item,
)
from policyengine_api.fastapi_routes.v2.reports.run_models import (
    RERUN_RESPONSES,
    RUN_LIST_RESPONSES,
    ReportRerunConflictResponse,
    ReportRerunRequest,
    ReportRunListResponse,
    RerunReportUnreadableResponse,
    report_run_list_result,
)
from policyengine_api.fastapi_routes.v2.simulation_resources_support import (
    SUBMISSION_ERROR_MAPPINGS,
    SUBMISSION_REFUSALS,
    created_record_unreadable_answer,
    simulation_resource_operation,
    unavailable_after_creation_answer,
)
from policyengine_api.fastapi_routes.v2.user_resources_support import (
    request_size_limit,
)
from policyengine_api.query_parameters import (
    ReportCollectionQuery,
    ReportCreateQuery,
    ReportDetailQuery,
    ReportRunsQuery,
)
from policyengine_api.services.v2.simulation_service.types import (
    SimulationServiceConflictError,
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.stored_reports.budget_window_results.types import (
    BudgetWindowResultUnreadableError,
)
from policyengine_api.services.v2.stored_reports.economy_results.types import (
    EconomyResultUnreadableError,
)
from policyengine_api.services.v2.stored_reports.household_results.types import (
    HouseholdResultUnreadableError,
)
from policyengine_api.services.v2.stored_reports.validators import (
    CreatedReportUnreadableError,
    ReportStorageError,
    RerunReportUnreadableError,
    StoredReportNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
        V2StoredReportResourceService,
    )

MAXIMUM_REPORT_REQUEST_BYTES = 16 * 1024
enforce_report_request_size = request_size_limit(
    MAXIMUM_REPORT_REQUEST_BYTES, label="16 KiB"
)
ReportCreateQueryDependency = Annotated[
    ReportCreateQuery, Depends(query_dependency(ReportCreateQuery))
]
ReportCollectionQueryDependency = Annotated[
    ReportCollectionQuery, Depends(query_dependency(ReportCollectionQuery))
]
ReportDetailQueryDependency = Annotated[
    ReportDetailQuery, Depends(query_dependency(ReportDetailQuery))
]
ReportRunsQueryDependency = Annotated[
    ReportRunsQuery, Depends(query_dependency(ReportRunsQuery))
]

# Refusals a caller can act on carry their own message and are not logged.
REPORT_REFUSALS: tuple[type[Exception], ...] = (
    StoredReportNotFoundError,
    *SUBMISSION_REFUSALS,
)
REPORT_ERROR_MAPPINGS = (
    V2ErrorMapping((StoredReportNotFoundError,), 404),
    *SUBMISSION_ERROR_MAPPINGS,
    V2ErrorMapping(
        (
            EconomyResultUnreadableError,
            HouseholdResultUnreadableError,
            BudgetWindowResultUnreadableError,
        ),
        500,
        "The report's stored result cannot be read",
    ),
    # SUBMISSION_ERROR_MAPPINGS answers a missing v2 database configuration.
    V2ErrorMapping((ReportStorageError,), 503, "V2 report storage is unavailable"),
)


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2StoredReportResourceService]:
    if dependencies.v2_stored_report_service_factory is not None:
        return dependencies.v2_stored_report_service_factory
    return _default_v2_stored_report_service_factory


OperationT = TypeVar("OperationT")


def _report_operation(
    operation: Callable[[], OperationT],
) -> OperationT | JSONResponse:
    return simulation_resource_operation(
        operation,
        REPORT_ERROR_MAPPINGS,
        refusals=REPORT_REFUSALS,
        event="v2_report_operation_failed",
        fallback_message="V2 report operation failed",
    )


def _create_report(
    service: V2StoredReportResourceService, body: ReportCreateRequest
) -> ReportDetailResponse | JSONResponse:
    """Create the report and answer it as stored.

    A report the simulation service created answers with its ``report_id``
    when it cannot be read back (502), and when the service failed its run
    and answered 503. Every other failure is raised, for the route's error
    mappings to answer.
    """
    try:
        report = service.create_report(body)
    except CreatedReportUnreadableError as error:
        return created_record_unreadable_answer(
            "v2_created_report_unreadable",
            error,
            CreatedReportUnreadableResponse(
                message=(
                    f"The simulation service created report {error.report_id}, "
                    "but it could not be read back. Read it with GET "
                    f"/v2/reports/{error.report_id}?country_id={error.country_id} "
                    "rather than submitting it again."
                ),
                report_id=error.report_id,
            ),
        )
    except SimulationServiceUnavailableError as error:
        if error.created_record_id is None:
            raise
        return unavailable_after_creation_answer(
            "v2_report_unavailable_after_creation",
            error,
            UnavailableAfterReportCreatedResponse(
                message=str(error), report_id=error.created_record_id
            ),
        )
    return ReportDetailResponse(result=ReportDetailResult(item=report_item(report)))


def _rerun_report(
    service: V2StoredReportResourceService,
    *,
    country_id: str,
    report_id: UUID,
    force: bool,
) -> ReportDetailResponse | JSONResponse:
    """Run the report again and answer it with its new run.

    The simulation service's refusal to run it again now answers 409 with
    the run it names, and a report that cannot be read back once its new run
    started answers 502 with its ``report_id``. Every other failure is
    raised, for the route's error mappings to answer.
    """
    try:
        report = service.rerun_report(
            country_id=country_id, report_id=report_id, force=force
        )
    except SimulationServiceConflictError as error:
        conflict = ReportRerunConflictResponse(message=str(error), run_id=error.run_id)
        return JSONResponse(status_code=409, content=conflict.model_dump(mode="json"))
    except RerunReportUnreadableError as error:
        return created_record_unreadable_answer(
            "v2_rerun_report_unreadable",
            error,
            RerunReportUnreadableResponse(
                message=(
                    "The simulation service started a new run of report "
                    f"{error.report_id}, but the report could not be read back. "
                    f"Read it with GET /v2/reports/{error.report_id}?country_id="
                    f"{error.country_id} rather than running it again."
                ),
                report_id=error.report_id,
            ),
        )
    return ReportDetailResponse(result=ReportDetailResult(item=report_item(report)))


def _add_report_run_routes(
    router: APIRouter, service_factory: Callable[[], V2StoredReportResourceService]
) -> None:
    """Add the routes that run a report again and list its runs."""

    @router.post(
        "/reports/{report_id}/runs",
        response_model=ReportDetailResponse,
        status_code=201,
        responses=RERUN_RESPONSES,
        summary="Run a report again",
        description=(
            "Checks the report as a new report of its kind is checked (the "
            "country has economy reports, or household calculations for a "
            "household report, and each policy its simulations name is stored and "
            "sets only parameters the running catalog version has), then has the "
            "simulation service create the report's new run, with the manual "
            "trigger, on its default worker's PolicyEngine.py version, and start "
            "it. Every earlier run is kept. Without force, each side reuses a "
            "run of its own simulation that succeeded on those versions; with "
            "force, both simulations are calculated again. A household report's "
            "sides are always calculated again, so force changes nothing for it. "
            "A budget window's new "
            "run is a budget-window run with a report run for each year, and "
            "with force each year calculates its simulations again. Answers the "
            "report as stored, whose newest run is then the new one, since no "
            "other run "
            "starts while it is pending or running: a report with a run pending "
            "or running answers 409 naming that run. Read the report again to "
            "follow the run."
        ),
    )
    def rerun_report(
        report_id: UUID,
        body: ReportRerunRequest,
        query: ReportRunsQueryDependency,
        _size: Annotated[None, Depends(enforce_report_request_size)],
    ) -> ReportDetailResponse | JSONResponse:
        def rerun() -> ReportDetailResponse | JSONResponse:
            return _rerun_report(
                service_factory(),
                country_id=query.country_id,
                report_id=report_id,
                force=body.force,
            )

        return _report_operation(rerun)

    @router.get(
        "/reports/{report_id}/runs",
        response_model=ReportRunListResponse,
        responses=RUN_LIST_RESPONSES,
        summary="List a report's runs",
        description=(
            "Lists every run of the report, newest first, whatever its status "
            "and versions, each with the country package and PolicyEngine.py "
            "versions it ran on, beside the versions the Public API runs now. A "
            "run on other versions than those is out of date. An economy or "
            "household report's runs are its report runs (kind economy or "
            "household); a budget window's are its budget-window runs, each "
            "with its years (kind budget_window). Reading starts no run."
        ),
    )
    def list_report_runs(
        report_id: UUID,
        query: ReportRunsQueryDependency,
    ) -> ReportRunListResponse | JSONResponse:
        def read() -> ReportRunListResponse:
            runs = service_factory().list_report_runs(
                country_id=query.country_id, report_id=report_id
            )
            return ReportRunListResponse(result=report_run_list_result(runs))

        return _report_operation(read)


def build_v2_report_router(dependencies: NativeRouteDependencies) -> APIRouter:
    """Build the report routes without opening a connection."""
    router = APIRouter(prefix="/v2", responses=REPORT_ERROR_RESPONSES)
    service_factory = _service_factory(dependencies)

    @router.post(
        "/reports",
        response_model=ReportDetailResponse,
        status_code=201,
        responses=CREATE_RESPONSES,
        summary="Create an economy report, a household report or a budget window",
        description=(
            "Checks that the country has economy reports and stores each named "
            "policy, and that the running catalog version has every parameter "
            "those policies set, then has the simulation service create the "
            "report, its two "
            "simulations and their runs on its default worker's PolicyEngine.py "
            "version, and start the run. A household report (kind household) "
            "is checked the same way, except that the country must have "
            "household calculations instead (a household-only country does), "
            "and the household it names must be stored in the country, with a "
            "default year; its simulations each calculate that household in its "
            "default year. A budget window (kind budget_window) is checked as an "
            "economy report is; the simulation service creates a budget-window "
            "run with a report run for each year, and starts its years. "
            "Answers the report as stored, with its "
            "pending run; read it again to follow the run. A created report "
            "that cannot be read back answers 502 with its report_id, and one "
            "whose run the simulation service failed before answering 503 "
            "answers 503 with its report_id."
        ),
    )
    def create_report(
        body: ReportCreateRequest,
        query: ReportCreateQueryDependency,
        _size: Annotated[None, Depends(enforce_report_request_size)],
    ) -> ReportDetailResponse | JSONResponse:
        if body.country_id != query.country_id:
            return v2_error_response(400, "Body country_id must match query country_id")

        def create() -> ReportDetailResponse | JSONResponse:
            return _create_report(service_factory(), body)

        return _report_operation(create)

    @router.get(
        "/reports",
        response_model=ReportListResponse,
        summary="List chosen reports, or find reports by their dataset-independent key",
        description=(
            "Lists the country's reports among the report_id values (at most "
            "25), in the order named and once each, with their newest runs, and "
            "each budget window's years, but without results, read in two "
            "queries. Unknown reports and other countries' are left out. With "
            "dataset_independent_key in place of report_id, lists the same way "
            "the country's reports whose dataset_independent_key it is, newest "
            "created first, at most the 25 created last: reports that differ "
            "only in their dataset, such as a national report and its "
            "local-area report (data_source local_area_dataset), and the same "
            "reports on another data release. Give one of the two, never both."
        ),
    )
    def list_reports(
        query: ReportCollectionQueryDependency,
    ) -> ReportListResponse | JSONResponse:
        def read() -> ReportListResponse:
            service = service_factory()
            if query.dataset_independent_key is None:
                reports = service.list_reports(
                    country_id=query.country_id, report_ids=query.report_id
                )
            else:
                reports = service.search_reports(
                    country_id=query.country_id,
                    dataset_independent_key=query.dataset_independent_key,
                )
            return ReportListResponse(
                result=ReportListResult(
                    items=[report_summary_item(report) for report in reports]
                )
            )

        return _report_operation(read)

    @router.get(
        "/reports/{report_id}",
        response_model=ReportDetailResponse,
        responses=READ_RESPONSES,
        summary="Read a report",
        description=(
            "Returns the report, its newest run whatever its status and "
            "versions, the versions the Public API runs now, and, once the newest "
            "run has succeeded, its result. An economy report's run is one report "
            "run and its result today's economy result. A household report's "
            "result is each simulation's calculated household, as "
            "/v2/household-calculations answers one, and a failed run gives each "
            "side's error. A budget window's run is a budget-window run with a "
            "report run per year, and its result today's budget-window format: "
            "each year's budget figures and their totals. A report with no run, "
            "such as one migrated from v1, answers its definition with no result; "
            "reading starts no run."
        ),
    )
    def get_report(
        report_id: UUID,
        query: ReportDetailQueryDependency,
    ) -> ReportDetailResponse | JSONResponse:
        def read() -> ReportDetailResponse:
            report = service_factory().get_report(
                country_id=query.country_id, report_id=report_id
            )
            return ReportDetailResponse(
                result=ReportDetailResult(item=report_item(report))
            )

        return _report_operation(read)

    _add_report_run_routes(router, service_factory)
    return router
