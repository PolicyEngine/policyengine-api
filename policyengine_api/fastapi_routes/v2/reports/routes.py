"""Native FastAPI routes for v2 reports.

The routes need no user credential: a user keeps a report through
``/v2/user-reports``. Reports, their runs and results are read from the
detailed-save tables the simulation service and its Modal workers write;
reading never calls the simulation service and never starts a run. Creating
a report checks it, has the simulation service create and start it, and
reads it back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse

from policyengine_api.data.v2.settings import V2ConfigurationError
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
    ReportDetailResponse,
    ReportDetailResult,
    ReportItem,
    ReportListResponse,
    ReportListResult,
    ReportSummaryItem,
)
from policyengine_api.fastapi_routes.v2.simulation_resources_support import (
    SUBMISSION_ERROR_MAPPINGS,
    SUBMISSION_REFUSALS,
    simulation_resource_operation,
)
from policyengine_api.fastapi_routes.v2.user_resources_support import (
    request_size_limit,
)
from policyengine_api.query_parameters import (
    ReportCollectionQuery,
    ReportCreateQuery,
    ReportDetailQuery,
)
from policyengine_api.services.v2.stored_reports.economy_results.types import (
    EconomyResultUnreadableError,
)
from policyengine_api.services.v2.stored_reports.validators import (
    ReportKindUnsupportedError,
    ReportStorageError,
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

# Refusals a caller can act on carry their own message and are not logged.
REPORT_REFUSALS: tuple[type[Exception], ...] = (
    StoredReportNotFoundError,
    ReportKindUnsupportedError,
    *SUBMISSION_REFUSALS,
)
REPORT_ERROR_MAPPINGS = (
    V2ErrorMapping((StoredReportNotFoundError,), 404),
    V2ErrorMapping((ReportKindUnsupportedError,), 422),
    *SUBMISSION_ERROR_MAPPINGS,
    V2ErrorMapping(
        (EconomyResultUnreadableError,),
        500,
        "The report's stored result cannot be read",
    ),
    V2ErrorMapping(
        (V2ConfigurationError, ReportStorageError),
        503,
        "V2 report storage is unavailable",
    ),
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


def build_v2_report_router(dependencies: NativeRouteDependencies) -> APIRouter:
    """Build the report routes without opening a connection."""
    router = APIRouter(prefix="/v2", responses=REPORT_ERROR_RESPONSES)
    service_factory = _service_factory(dependencies)

    @router.post(
        "/reports",
        response_model=ReportDetailResponse,
        status_code=201,
        responses=CREATE_RESPONSES,
        summary="Create an economy report",
        description=(
            "Checks that the country has economy reports and stores each named "
            "policy, then has the simulation service create the report, its two "
            "simulations and their runs on its default worker's PolicyEngine.py "
            "version, and start the run. Answers the report as stored, with its "
            "pending run; read it again to follow the run."
        ),
    )
    def create_report(
        body: ReportCreateRequest,
        query: ReportCreateQueryDependency,
        _size: Annotated[None, Depends(enforce_report_request_size)],
    ) -> ReportDetailResponse | JSONResponse:
        if body.country_id != query.country_id:
            return v2_error_response(400, "Body country_id must match query country_id")

        def create() -> ReportDetailResponse:
            report = service_factory().create_report(body)
            return ReportDetailResponse(
                result=ReportDetailResult(item=ReportItem.from_read(report))
            )

        return _report_operation(create)

    @router.get(
        "/reports",
        response_model=ReportListResponse,
        summary="List chosen economy reports",
        description=(
            "Lists the country's economy reports among the report_id values (at "
            "most 25), in the order named and once each, with their newest runs "
            "but without results, read in one query. Unknown reports, other "
            "countries' and reports of other kinds are left out."
        ),
    )
    def list_reports(
        query: ReportCollectionQueryDependency,
    ) -> ReportListResponse | JSONResponse:
        def read() -> ReportListResponse:
            reports = service_factory().list_reports(
                country_id=query.country_id, report_ids=query.report_id
            )
            return ReportListResponse(
                result=ReportListResult(
                    items=[ReportSummaryItem.from_summary(report) for report in reports]
                )
            )

        return _report_operation(read)

    @router.get(
        "/reports/{report_id}",
        response_model=ReportDetailResponse,
        responses=READ_RESPONSES,
        summary="Read an economy report",
        description=(
            "Returns the report, its newest run whatever its status and "
            "versions, the versions the Public API runs now, and, once the "
            "newest run has succeeded, its result in today's economy result "
            "format. A report with no run, such as one migrated from v1, "
            "answers its definition with no result; reading starts no run."
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
                result=ReportDetailResult(item=ReportItem.from_read(report))
            )

        return _report_operation(read)

    return router
