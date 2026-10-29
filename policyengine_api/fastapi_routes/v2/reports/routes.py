"""Native FastAPI routes for v2 reports: economy reports and household reports.

Reports are calculated and stored by the Simulation Entrypoint; these routes
need no user credential. A user keeps a report through ``/v2/user-reports``.
A submission names its kind; ``V2ReportService`` sends each operation to the
economy or household report service.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, Path
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import (
    _default_v2_economy_report_service_factory,
    _default_v2_household_report_service_factory,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.errors import (
    V2ErrorMapping,
    failure_log_attributes,
    run_v2_operation,
    v2_error_response,
)
from policyengine_api.fastapi_routes.v2.reports.household_response_models import (
    HouseholdReportItem,
    HouseholdReportRunItem,
    HouseholdReportSummaryItem,
)
from policyengine_api.fastapi_routes.v2.reports.request_models import (
    EconomyReportRunRequest,
    ReportCreateRequest,
)
from policyengine_api.fastapi_routes.v2.reports.response_models import (
    READ_RESPONSES,
    REPORT_ERROR_RESPONSES,
    RUN_RESPONSES,
    RUNS_NOT_FOUND_RESPONSE,
    SUBMIT_RESPONSES,
    ReportDetailResponse,
    ReportDetailResult,
    ReportItem,
    ReportListResponse,
    ReportListResult,
    ReportRunDetailResponse,
    ReportRunDetailResult,
    ReportRunItem,
    ReportRunListResponse,
    ReportRunListResult,
    ReportSummaryItem,
)
from policyengine_api.fastapi_routes.v2.user_resources import request_size_limit
from policyengine_api.query_parameters import (
    MAXIMUM_LEGACY_RESOURCE_ID,
    ReportCollectionQuery,
    ReportCreateQuery,
    ReportDetailQuery,
)
from policyengine_api.services.v2.economy_reports.validators import (
    EconomyReportNotFoundError,
    EconomyReportsUnsupportedError,
)
from policyengine_api.services.v2.household_reports.types import (
    HouseholdReportRecord,
    HouseholdReportRunRecord,
)
from policyengine_api.services.v2.household_reports.validators import (
    HouseholdReportNotFoundError,
    HouseholdReportsUnsupportedError,
    HouseholdReportYearError,
)
from policyengine_api.services.v2.households.validators import HouseholdNotFoundError
from policyengine_api.services.v2.policies.validators import PolicyNotFoundError
from policyengine_api.services.v2.report_kinds.services import V2ReportService
from policyengine_api.services.v2.report_kinds.validators import ReportNotFoundError
from policyengine_api.services.v2.simulation_entrypoint.types import (
    SimulationRecordUnreadableError,
    SimulationRequestRefusedError,
    SimulationServiceUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
    )
    from policyengine_api.services.v2.simulation_entrypoint.types import (
        EconomyReportRecord,
        EconomyReportRunRecord,
    )

logger = logging.getLogger(__name__)

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
LegacyReportNumber = Annotated[
    int,
    Path(
        ge=1,
        le=MAXIMUM_LEGACY_RESOURCE_ID,
        description="The v1 report output number the report was migrated from",
    ),
]

# Refusals a caller can act on carry their own message.
REPORT_REFUSALS: tuple[type[Exception], ...] = (
    EconomyReportsUnsupportedError,
    SimulationRequestRefusedError,
    EconomyReportNotFoundError,
    HouseholdReportsUnsupportedError,
    HouseholdReportYearError,
    HouseholdReportNotFoundError,
    HouseholdNotFoundError,
    PolicyNotFoundError,
    ReportNotFoundError,
)
REPORT_ERROR_MAPPINGS = (
    V2ErrorMapping(
        (
            ReportNotFoundError,
            EconomyReportNotFoundError,
            HouseholdReportNotFoundError,
            HouseholdNotFoundError,
            PolicyNotFoundError,
        ),
        404,
    ),
    V2ErrorMapping(
        (SimulationRecordUnreadableError,),
        502,
        "The simulation service cannot read back this report's result",
    ),
    V2ErrorMapping(
        (
            EconomyReportsUnsupportedError,
            HouseholdReportsUnsupportedError,
            HouseholdReportYearError,
            SimulationRequestRefusedError,
        ),
        422,
    ),
    V2ErrorMapping(
        (SimulationServiceUnavailableError,),
        503,
        "The simulation service is unavailable",
    ),
    V2ErrorMapping(
        (V2ConfigurationError, SQLAlchemyError),
        503,
        "V2 report persistence is unavailable",
    ),
)

OperationT = TypeVar("OperationT")


def _log_failure(error: Exception) -> None:
    """Record why an operation failed, unless it was a refusal the caller sees.

    Errors are recorded by type and the locations of their innermost frames,
    not their messages, which can carry bound SQL parameters; only the
    simulation service's unavailability adds its reason. Logging never
    changes the response.
    """
    with contextlib.suppress(Exception):
        attributes = failure_log_attributes(error)
        if isinstance(error, SimulationServiceUnavailableError):
            attributes["reason"] = str(error)[:500]
        logger.error(
            "v2_report_operation_failed",
            extra={"policyengine_attributes": attributes},
        )


def _report_operation(
    operation: Callable[[], OperationT],
) -> OperationT | JSONResponse:
    def logged() -> OperationT:
        try:
            return operation()
        except Exception as error:
            if not isinstance(error, REPORT_REFUSALS):
                _log_failure(error)
            raise

    return run_v2_operation(
        logged,
        REPORT_ERROR_MAPPINGS,
        fallback_message="V2 report operation failed",
    )


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2ReportService]:
    economy_factory = (
        dependencies.v2_economy_report_service_factory
        or _default_v2_economy_report_service_factory
    )
    household_factory = (
        dependencies.v2_household_report_service_factory
        or _default_v2_household_report_service_factory
    )
    return lambda: V2ReportService(
        economy_reports=economy_factory, household_reports=household_factory
    )


def _report_detail(
    report: EconomyReportRecord | HouseholdReportRecord,
) -> ReportDetailResponse:
    item = (
        HouseholdReportItem.from_record(report)
        if isinstance(report, HouseholdReportRecord)
        else ReportItem.from_record(report)
    )
    return ReportDetailResponse(result=ReportDetailResult(item=item))


def _report_list(
    reports: tuple[EconomyReportRecord | HouseholdReportRecord, ...],
) -> ReportListResponse:
    return ReportListResponse(
        result=ReportListResult(
            items=[
                HouseholdReportSummaryItem.from_record(report)
                if isinstance(report, HouseholdReportRecord)
                else ReportSummaryItem.from_record(report)
                for report in reports
            ]
        )
    )


def _report_run_detail(
    report_run: EconomyReportRunRecord | HouseholdReportRunRecord,
) -> ReportRunDetailResponse:
    item = (
        HouseholdReportRunItem.from_record(report_run)
        if isinstance(report_run, HouseholdReportRunRecord)
        else ReportRunItem.from_record(report_run)
    )
    return ReportRunDetailResponse(result=ReportRunDetailResult(item=item))


def _report_run_list(
    runs: tuple[EconomyReportRunRecord, ...],
) -> ReportRunListResponse:
    return ReportRunListResponse(
        result=ReportRunListResult(
            items=[ReportRunItem.from_record(run) for run in runs]
        )
    )


def build_v2_report_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the report routes without opening a connection."""
    router = APIRouter(prefix="/v2", responses=REPORT_ERROR_RESPONSES)
    service_factory = _service_factory(dependencies)

    @router.post(
        "/reports",
        response_model=ReportDetailResponse,
        status_code=201,
        responses=SUBMIT_RESPONSES,
        summary="Submit an economy or household report",
        description=(
            "Creates the report, its simulations and its first run in the "
            "simulation service, on the country's current catalog version, and "
            "starts the run. Read the report to follow it. An economy report "
            "(kind economy) compares two policies across a region; a country "
            "without economy reports, such as a household-only one, is refused "
            "with 422 before anything is created. A household report (kind "
            "household) calculates a household stored through /v2/households "
            "under a baseline and an optional reform, for the household's "
            "default year; it needs the country's household calculations, which "
            "a household-only country has, and a household and policies of the "
            "country (404 otherwise) with a default year (422 otherwise), all "
            "checked before anything is created."
        ),
    )
    def submit_report(
        body: ReportCreateRequest,
        query: ReportCreateQueryDependency,
        _size: Annotated[None, Depends(enforce_report_request_size)],
    ) -> ReportDetailResponse | JSONResponse:
        if body.country_id != query.country_id:
            return v2_error_response(400, "Body country_id must match query country_id")
        return _report_operation(
            lambda: _report_detail(
                service_factory().submit_report(
                    country_id=query.country_id, report_input=body
                )
            )
        )

    @router.get(
        "/reports",
        response_model=ReportListResponse,
        summary="List chosen reports",
        description=(
            "Lists the country's reports of both kinds among the report_id "
            "values (at most 25), in that order and once each, with their "
            "status and newest run but without economy results or household "
            "calculations. Unknown reports and other countries' are left out. "
            "Listing does not start the first run of an economy report that "
            "has none; reading it does."
        ),
    )
    def list_reports(
        query: ReportCollectionQueryDependency,
    ) -> ReportListResponse | JSONResponse:
        return _report_operation(
            lambda: _report_list(
                service_factory().list_reports(
                    country_id=query.country_id, report_ids=query.report_id
                )
            )
        )

    @router.get(
        "/reports/by-legacy-number/{legacy_report_id}",
        response_model=ReportDetailResponse,
        responses=READ_RESPONSES,
        summary="Find the report migrated from a v1 report number",
        description=(
            "Answers as reading the report by its ID, including starting the "
            "first run of a report that has none. 404 means no report of this "
            "country was migrated from that number."
        ),
    )
    def get_report_by_legacy_number(
        legacy_report_id: LegacyReportNumber,
        query: ReportDetailQueryDependency,
    ) -> ReportDetailResponse | JSONResponse:
        return _report_operation(
            lambda: _report_detail(
                service_factory().get_report_by_legacy_number(
                    country_id=query.country_id, legacy_report_id=legacy_report_id
                )
            )
        )

    @router.get(
        "/reports/{report_id}",
        response_model=ReportDetailResponse,
        responses=READ_RESPONSES,
        summary="Read an economy or household report",
        description=(
            "Returns the report, its newest run and, once that run succeeded, its "
            "result: an economy report's result, or a household report's "
            "calculated households in the run's baseline and reform. An economy "
            "report with no run, such as one migrated from v1, is calculated the "
            "first time it is read: the read starts a run with the system "
            "trigger on the current catalog version and answers with it. If the "
            "simulation service cannot run it, the report is returned not run."
        ),
    )
    def get_report(
        report_id: UUID,
        query: ReportDetailQueryDependency,
    ) -> ReportDetailResponse | JSONResponse:
        return _report_operation(
            lambda: _report_detail(
                service_factory().get_report(
                    country_id=query.country_id, report_id=report_id
                )
            )
        )

    @router.post(
        "/reports/{report_id}/runs",
        response_model=ReportRunDetailResponse,
        status_code=201,
        responses=RUN_RESPONSES,
        summary="Run an economy or household report again",
        description=(
            "Runs the report on the country's current catalog version with the "
            "manual trigger, and answers with the new run. Simulation runs that "
            "already exist for that version and year are reused unless force is "
            "set, which calculates both simulations again; a household report "
            "reuses calculations that are unfinished or succeeded within the "
            "last 28 days. A country without economy reports, such as a "
            "household-only one, can run only its household reports again; its "
            "other report IDs are refused with 422, and a country without "
            "household calculations cannot run household reports again (422), "
            "before the simulation service is asked to run them."
        ),
    )
    def run_report(
        report_id: UUID,
        body: EconomyReportRunRequest,
        query: ReportDetailQueryDependency,
        _size: Annotated[None, Depends(enforce_report_request_size)],
    ) -> ReportRunDetailResponse | JSONResponse:
        return _report_operation(
            lambda: _report_run_detail(
                service_factory().run_report(
                    country_id=query.country_id, report_id=report_id, force=body.force
                )
            )
        )

    @router.get(
        "/reports/{report_id}/runs",
        response_model=ReportRunListResponse,
        responses=RUNS_NOT_FOUND_RESPONSE,
        summary="List an economy report's runs",
        description=(
            "Every run of the report, newest first, each with the catalog version "
            "and PolicyEngine.py version it ran on. Only economy reports list "
            "their runs; a household report's newest run is in the report."
        ),
    )
    def list_report_runs(
        report_id: UUID,
        query: ReportDetailQueryDependency,
    ) -> ReportRunListResponse | JSONResponse:
        return _report_operation(
            lambda: _report_run_list(
                service_factory().list_report_runs(
                    country_id=query.country_id, report_id=report_id
                )
            )
        )

    return router
