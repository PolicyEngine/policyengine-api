"""Native FastAPI routes for v2 economy reports.

Reports are calculated and stored by the Simulation Entrypoint; these routes
need no user credential. A user keeps a report through ``/v2/user-reports``.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Annotated, TypeVar

from fastapi import APIRouter, Depends
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
)
from policyengine_api.fastapi_routes.v2.reports.response_models import (
    REPORT_ERROR_RESPONSES,
    ReportDetailResponse,
    ReportDetailResult,
    ReportItem,
)
from policyengine_api.fastapi_routes.v2.user_resources import request_size_limit
from policyengine_api.query_parameters import ReportCreateQuery
from policyengine_api.services.v2.economy_reports.types import (
    SimulationRequestRefusedError,
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.economy_reports.validators import (
    EconomyReportsUnsupportedError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
        V2EconomyReportResourceService,
    )

logger = logging.getLogger(__name__)

MAXIMUM_REPORT_REQUEST_BYTES = 16 * 1024
enforce_report_request_size = request_size_limit(
    MAXIMUM_REPORT_REQUEST_BYTES, label="16 KiB"
)

ReportCreateQueryDependency = Annotated[
    ReportCreateQuery, Depends(query_dependency(ReportCreateQuery))
]

# Refusals a caller can act on carry their own message.
REPORT_REFUSALS: tuple[type[Exception], ...] = (
    EconomyReportsUnsupportedError,
    SimulationRequestRefusedError,
)
REPORT_ERROR_MAPPINGS = (
    V2ErrorMapping(REPORT_REFUSALS, 422),
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

        def submit() -> ReportDetailResponse:
            report = service_factory().submit_report(
                country_id=query.country_id, report_input=body
            )
            return ReportDetailResponse(
                result=ReportDetailResult(item=ReportItem.from_record(report))
            )

        return _report_operation(submit)

    return router
