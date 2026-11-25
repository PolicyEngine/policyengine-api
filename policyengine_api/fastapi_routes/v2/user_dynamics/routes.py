"""Native FastAPI routes for users' saved dynamics."""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse, Response

from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2UserDynamicResourceService,
    _default_v2_user_dynamic_service_factory,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.errors_support import v2_error_response
from policyengine_api.fastapi_routes.v2.user_dynamics.request_models import (
    UserDynamicCreateRequest,
    UserDynamicPatchRequest,
)
from policyengine_api.fastapi_routes.v2.user_dynamics.response_models import (
    USER_DYNAMIC_ERROR_RESPONSES,
    UserDynamicDetailResponse,
    UserDynamicDetailResult,
    UserDynamicItem,
    UserDynamicPageResponse,
    UserDynamicPageResult,
)
from policyengine_api.fastapi_routes.v2.user_resources_support import (
    enforce_user_write_request_size,
    user_resource_operation,
)
from policyengine_api.query_parameters import (
    CountryQuery,
    UserDynamicCollectionQuery,
)
from policyengine_api.services.v2.identity.types import AccountPrincipal
from policyengine_api.services.v2.user_dynamics.types import UserDynamicFilter

CountryQueryDependency = Annotated[
    CountryQuery, Depends(query_dependency(CountryQuery))
]
UserDynamicCollectionQueryDependency = Annotated[
    UserDynamicCollectionQuery,
    Depends(query_dependency(UserDynamicCollectionQuery)),
]


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2UserDynamicResourceService]:
    if dependencies.v2_user_dynamic_service_factory is not None:
        return dependencies.v2_user_dynamic_service_factory
    return _default_v2_user_dynamic_service_factory


def _create_user_dynamic(
    service_factory: Callable[[], V2UserDynamicResourceService],
    body: UserDynamicCreateRequest,
    query: CountryQuery,
    principal: AccountPrincipal,
) -> UserDynamicDetailResponse | JSONResponse:
    """Save a dynamic once the body and query agree on its country."""
    if body.country_id != query.country_id:
        return v2_error_response(
            400,
            "Body country_id must match query country_id",
        )

    def create() -> UserDynamicDetailResponse:
        item = service_factory().create_user_dynamic(
            principal=principal,
            association_input=body,
        )
        return UserDynamicDetailResponse(
            result=UserDynamicDetailResult(item=UserDynamicItem.from_read(item))
        )

    return user_resource_operation(create)


def build_v2_user_dynamic_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the saved-dynamic routes without opening a connection.

    Authentication is a router-level dependency, so a missing or invalid
    credential is rejected before query or body validation.
    """
    require_user = dependencies.require_user
    router = APIRouter(
        prefix="/v2",
        responses=USER_DYNAMIC_ERROR_RESPONSES,
        dependencies=[
            Depends(require_user),
            Depends(enforce_user_write_request_size),
        ],
    )
    service_factory = _service_factory(dependencies)

    @router.post(
        "/user-dynamics",
        response_model=UserDynamicDetailResponse,
        status_code=201,
        summary="Save a dynamic for the current user",
        description=(
            "Requires a bearer access token or the PolicyEngine-Unauthenticated-User "
            "header; the owner is taken from that credential. dynamic_id names a "
            "dynamic (POST /v2/dynamics) stored in the same country: an unknown "
            "one is not found (404), and another country's is refused (400). A "
            "user may save the same dynamic more than once."
        ),
    )
    def create_user_dynamic(
        body: UserDynamicCreateRequest,
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> UserDynamicDetailResponse | JSONResponse:
        return _create_user_dynamic(service_factory, body, query, principal)

    @router.get(
        "/user-dynamics/{association_id}",
        response_model=UserDynamicDetailResponse,
        summary="Read one of the current user's saved dynamics",
    )
    def get_user_dynamic(
        association_id: UUID,
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> UserDynamicDetailResponse | JSONResponse:
        def read() -> UserDynamicDetailResponse:
            item = service_factory().get_user_dynamic(
                principal=principal,
                country_id=query.country_id,
                association_id=association_id,
            )
            return UserDynamicDetailResponse(
                result=UserDynamicDetailResult(item=UserDynamicItem.from_read(item))
            )

        return user_resource_operation(read)

    @router.get(
        "/user-dynamics",
        response_model=UserDynamicPageResponse,
        summary="List the current user's saved dynamics",
        description=(
            "Oldest first. dynamic_id keeps only the saved dynamics that name "
            "that dynamic."
        ),
    )
    def get_user_dynamics(
        query: UserDynamicCollectionQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> UserDynamicPageResponse | JSONResponse:
        def read() -> UserDynamicPageResponse:
            page = service_factory().list_user_dynamics(
                principal=principal,
                country_id=query.country_id,
                dynamic_filter=UserDynamicFilter(dynamic_id=query.dynamic_id),
                offset=query.offset,
                limit=query.limit,
            )
            return UserDynamicPageResponse(result=UserDynamicPageResult.from_page(page))

        return user_resource_operation(read)

    @router.patch(
        "/user-dynamics/{association_id}",
        response_model=UserDynamicDetailResponse,
        summary="Rename or repoint one of the current user's saved dynamics",
        description=(
            "The row keeps its id, owner and creation time. dynamic_id points it "
            "at another dynamic stored in the same country, and can't be null."
        ),
    )
    def patch_user_dynamic_route(
        association_id: UUID,
        body: UserDynamicPatchRequest,
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> UserDynamicDetailResponse | JSONResponse:
        def patch() -> UserDynamicDetailResponse:
            item = service_factory().patch_user_dynamic(
                principal=principal,
                country_id=query.country_id,
                association_id=association_id,
                association_input=body,
            )
            return UserDynamicDetailResponse(
                result=UserDynamicDetailResult(item=UserDynamicItem.from_read(item))
            )

        return user_resource_operation(patch)

    @router.delete(
        "/user-dynamics/{association_id}",
        response_model=None,
        status_code=204,
        response_class=Response,
        summary="Delete one of the current user's saved dynamics",
        description="The dynamic it names is kept.",
    )
    def delete_user_dynamic_route(
        association_id: UUID,
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> Response | JSONResponse:
        def delete() -> Response:
            service_factory().delete_user_dynamic(
                principal=principal,
                country_id=query.country_id,
                association_id=association_id,
            )
            return Response(status_code=204)

        return user_resource_operation(delete)

    return router
