"""Native FastAPI routes for v2 user-report associations.

The owner routes need a credential. A saved report's ID is also its
shareable link, read without one through ``/v2/shared-reports``.
"""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse, Response

from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2UserReportResourceService,
    _default_v2_user_report_service_factory,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.errors import (
    V2ErrorResponse,
    v2_error_response,
)
from policyengine_api.fastapi_routes.v2.user_reports.request_models import (
    UserReportCreateRequest,
    UserReportPatchRequest,
)
from policyengine_api.fastapi_routes.v2.user_reports.response_models import (
    SharedUserReportDetailResponse,
    SharedUserReportDetailResult,
    SharedUserReportItem,
    UserReportDetailResponse,
    UserReportDetailResult,
    UserReportItem,
    UserReportPageResponse,
    UserReportPageResult,
)
from policyengine_api.fastapi_routes.v2.user_resources import (
    USER_RESOURCE_ERROR_RESPONSES,
    enforce_user_write_request_size,
    user_resource_operation,
)
from policyengine_api.query_parameters import (
    CountryQuery,
    UserReportCollectionQuery,
)
from policyengine_api.services.v2.identity.types import AccountPrincipal

SHARED_REPORT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {
        "model": V2ErrorResponse,
        "description": "No saved report has this ID in this country.",
    },
    422: {
        "model": V2ErrorResponse,
        "description": "The ID or the query does not match the schema.",
    },
    500: USER_RESOURCE_ERROR_RESPONSES[500],
    503: USER_RESOURCE_ERROR_RESPONSES[503],
}


CountryQueryDependency = Annotated[
    CountryQuery, Depends(query_dependency(CountryQuery))
]
UserReportCollectionQueryDependency = Annotated[
    UserReportCollectionQuery, Depends(query_dependency(UserReportCollectionQuery))
]


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2UserReportResourceService]:
    if dependencies.v2_user_report_service_factory is not None:
        return dependencies.v2_user_report_service_factory
    return _default_v2_user_report_service_factory


def _create_user_report(
    service_factory: Callable[[], V2UserReportResourceService],
    body: UserReportCreateRequest,
    query: CountryQuery,
    principal: AccountPrincipal,
) -> UserReportDetailResponse | JSONResponse:
    """Create an association once the body and query agree on its country."""
    if body.country_id != query.country_id:
        return v2_error_response(400, "Body country_id must match query country_id")

    def create() -> UserReportDetailResponse:
        item = service_factory().create_user_report(
            principal=principal,
            association_input=body,
        )
        return UserReportDetailResponse(
            result=UserReportDetailResult(item=UserReportItem.from_read(item))
        )

    return user_resource_operation(create)


def build_v2_user_report_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build user association routes without opening a connection.

    Authentication is a router-level dependency, so a missing or invalid
    credential is rejected before query or body validation.
    """
    require_user = dependencies.require_user
    router = APIRouter(
        prefix="/v2",
        responses=USER_RESOURCE_ERROR_RESPONSES,
        dependencies=[
            Depends(require_user),
            Depends(enforce_user_write_request_size),
        ],
    )
    service_factory = _service_factory(dependencies)

    @router.post(
        "/user-reports",
        response_model=UserReportDetailResponse,
        status_code=201,
        summary="Save a report for the current user",
        description=(
            "Requires a bearer access token or the PolicyEngine-Unauthenticated-User "
            "header; the owner is taken from that credential. "
            "The body names a v2 report (report_id), checked with the simulation "
            "service, a v1 report output (legacy_report_id), checked in the v1 "
            "database, or both; with both, the v2 report must be the one migrated "
            "from that v1 report output (400 otherwise). An optional "
            "user_policy_id must name the same user's saved policy in the same "
            "country."
        ),
    )
    def create_user_report(
        body: UserReportCreateRequest,
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> UserReportDetailResponse | JSONResponse:
        return _create_user_report(service_factory, body, query, principal)

    @router.get(
        "/user-reports/{association_id}",
        response_model=UserReportDetailResponse,
        summary="Read one of the current user's saved reports",
    )
    def get_user_report(
        association_id: UUID,
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> UserReportDetailResponse | JSONResponse:
        def read() -> UserReportDetailResponse:
            item = service_factory().get_user_report(
                principal=principal,
                country_id=query.country_id,
                association_id=association_id,
            )
            return UserReportDetailResponse(
                result=UserReportDetailResult(item=UserReportItem.from_read(item))
            )

        return user_resource_operation(read)

    @router.get(
        "/user-reports",
        response_model=UserReportPageResponse,
        summary="List the current user's saved reports",
    )
    def get_user_reports(
        query: UserReportCollectionQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> UserReportPageResponse | JSONResponse:
        def read() -> UserReportPageResponse:
            page = service_factory().list_user_reports(
                principal=principal,
                country_id=query.country_id,
                legacy_report_id=query.legacy_report_id,
                offset=query.offset,
                limit=query.limit,
            )
            return UserReportPageResponse(result=UserReportPageResult.from_page(page))

        return user_resource_operation(read)

    @router.patch(
        "/user-reports/{association_id}",
        response_model=UserReportDetailResponse,
        summary="Update or repoint one of the current user's saved reports",
    )
    def patch_user_report_route(
        association_id: UUID,
        body: UserReportPatchRequest,
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> UserReportDetailResponse | JSONResponse:
        def patch() -> UserReportDetailResponse:
            item = service_factory().patch_user_report(
                principal=principal,
                country_id=query.country_id,
                association_id=association_id,
                association_input=body,
            )
            return UserReportDetailResponse(
                result=UserReportDetailResult(item=UserReportItem.from_read(item))
            )

        return user_resource_operation(patch)

    @router.delete(
        "/user-reports/{association_id}",
        response_model=None,
        status_code=204,
        response_class=Response,
        summary="Delete one of the current user's saved reports",
    )
    def delete_user_report_route(
        association_id: UUID,
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> Response | JSONResponse:
        def delete() -> Response:
            service_factory().delete_user_report(
                principal=principal,
                country_id=query.country_id,
                association_id=association_id,
            )
            return Response(status_code=204)

        return user_resource_operation(delete)

    return router


def build_v2_shared_report_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the credential-free read of a saved report by its link."""
    router = APIRouter(prefix="/v2", responses=SHARED_REPORT_ERROR_RESPONSES)
    service_factory = _service_factory(dependencies)

    @router.get(
        "/shared-reports/{association_id}",
        response_model=SharedUserReportDetailResponse,
        summary="Read a saved report by its shareable link",
        description=(
            "Needs no credential: a saved report's ID is its link, and anyone "
            "holding it can read the report. The owner and the owner's "
            "saved-reform IDs are left out; the reform the report was compared "
            "with is named instead."
        ),
    )
    def get_shared_report(
        association_id: UUID,
        query: CountryQueryDependency,
    ) -> SharedUserReportDetailResponse | JSONResponse:
        def read() -> SharedUserReportDetailResponse:
            item = service_factory().get_shared_user_report(
                country_id=query.country_id,
                association_id=association_id,
            )
            return SharedUserReportDetailResponse(
                result=SharedUserReportDetailResult(
                    item=SharedUserReportItem.from_read(item)
                )
            )

        return user_resource_operation(read)

    return router
