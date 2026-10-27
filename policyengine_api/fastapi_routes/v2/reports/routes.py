"""Native FastAPI routes for v2 economy reports.

Reports are calculated and stored by the Simulation Entrypoint; these routes
need no user credential. A user keeps a report through ``/v2/user-reports``.
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
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.errors import (
    V2ErrorMapping,
    run_v2_operation,
    v2_error_response,
)
from policyengine_api.fastapi_routes.v2.reports.request_models import (
    EconomyReportCreateRequest,
    EconomyReportRunRequest,
)
from policyengine_api.fastapi_routes.v2.reports.response_models import (
    REPORT_ERROR_RESPONSES,
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
from policyengine_api.services.v2.simulation_entrypoint.types import (
    SimulationRequestRefusedError,
    SimulationServiceUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
        V2EconomyReportResourceService,
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
)
REPORT_ERROR_MAPPINGS = (
    V2ErrorMapping((EconomyReportNotFoundError,), 404),
    V2ErrorMapping(
        (EconomyReportsUnsupportedError, SimulationRequestRefusedError), 422
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

    Database errors are recorded by type only, because their messages can
    carry bound SQL parameters. Logging never changes the response.
    """
    with contextlib.suppress(Exception):
        attributes = {"error_type": type(error).__name__}
        if isinstance(error, SimulationServiceUnavailableError):
            attributes["reason"] = str(error)[:500]
        logger.warning(
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
) -> Callable[[], V2EconomyReportResourceService]:
    if dependencies.v2_economy_report_service_factory is not None:
        return dependencies.v2_economy_report_service_factory
    return _default_v2_economy_report_service_factory


def _report_detail(report: EconomyReportRecord) -> ReportDetailResponse:
    return ReportDetailResponse(
        result=ReportDetailResult(item=ReportItem.from_record(report))
    )


def _report_list(reports: tuple[EconomyReportRecord, ...]) -> ReportListResponse:
    return ReportListResponse(
        result=ReportListResult(
            items=[ReportSummaryItem.from_record(report) for report in reports]
        )
    )


def _report_run_detail(report_run: EconomyReportRunRecord) -> ReportRunDetailResponse:
    return ReportRunDetailResponse(
        result=ReportRunDetailResult(item=ReportRunItem.from_record(report_run))
    )


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
    """Build the economy report routes without opening a connection."""
    router = APIRouter(prefix="/v2", responses=REPORT_ERROR_RESPONSES)
    service_factory = _service_factory(dependencies)

    @router.post(
        "/reports",
        response_model=ReportDetailResponse,
        status_code=201,
        summary="Submit an economy report",
        description=(
            "Creates the baseline and reform simulations, the report and its "
            "first run in the simulation service, on the country's current "
            "catalog version, and starts the run. Read the report to follow it. "
            "A country without economy reports, such as a household-only one, "
            "is refused with 422 before anything is created."
        ),
    )
    def submit_report(
        body: EconomyReportCreateRequest,
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
        summary="List chosen economy reports",
        description=(
            "Lists the country's reports among the report_id values (at most "
            "25), in that order and once each, with their status and newest run "
            "but without results. Unknown reports and other countries' are left "
            "out. Listing does not start the first run of a report that has "
            "none; reading it does."
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
        summary="Read an economy report",
        description=(
            "Returns the report, its newest run and, once that run succeeded, its "
            "result. A report with no run, such as one migrated from v1, is "
            "calculated the first time it is read: the read starts a run with "
            "the system trigger on the current catalog version and answers with "
            "it. If the simulation service cannot run it, the report is "
            "returned not run."
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
        summary="Run an economy report again",
        description=(
            "Runs the report on the country's current catalog version with the "
            "manual trigger. Simulation runs that already exist for that version "
            "and year are reused unless force is set, which calculates both "
            "simulations again. A country without economy reports is refused "
            "with 422 before the simulation service is asked."
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
        summary="List an economy report's runs",
        description=(
            "Every run of the report, newest first, each with the catalog version "
            "and PolicyEngine.py version it ran on."
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
