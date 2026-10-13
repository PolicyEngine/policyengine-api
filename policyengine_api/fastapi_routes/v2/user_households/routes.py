"""Native FastAPI routes for v2 user-household associations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse, Response

from policyengine_api.fastapi_routes.dependencies import (
    _default_v2_user_household_service_factory,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.errors import v2_error_response
from policyengine_api.fastapi_routes.v2.user_households.request_models import (
    UserHouseholdCreateRequest,
    UserHouseholdPatchRequest,
)
from policyengine_api.fastapi_routes.v2.user_households.response_models import (
    USER_HOUSEHOLD_ERROR_RESPONSES,
    UserHouseholdDetailResponse,
    UserHouseholdDetailResult,
    UserHouseholdItem,
    UserHouseholdPageResponse,
    UserHouseholdPageResult,
)
from policyengine_api.fastapi_routes.v2.user_resources import (
    enforce_user_write_request_size,
    user_resource_operation,
)
from policyengine_api.query_parameters import (
    UserHouseholdCollectionQuery,
    UserHouseholdCreateQuery,
    UserHouseholdDeleteQuery,
    UserHouseholdDetailQuery,
    UserHouseholdUpdateQuery,
)
from policyengine_api.services.v2.identity.types import AccountPrincipal

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
        V2UserHouseholdResourceService,
    )


UserHouseholdCreateQueryDependency = Annotated[
    UserHouseholdCreateQuery, Depends(query_dependency(UserHouseholdCreateQuery))
]
UserHouseholdDetailQueryDependency = Annotated[
    UserHouseholdDetailQuery, Depends(query_dependency(UserHouseholdDetailQuery))
]
UserHouseholdCollectionQueryDependency = Annotated[
    UserHouseholdCollectionQuery,
    Depends(query_dependency(UserHouseholdCollectionQuery)),
]
UserHouseholdUpdateQueryDependency = Annotated[
    UserHouseholdUpdateQuery, Depends(query_dependency(UserHouseholdUpdateQuery))
]
UserHouseholdDeleteQueryDependency = Annotated[
    UserHouseholdDeleteQuery, Depends(query_dependency(UserHouseholdDeleteQuery))
]


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2UserHouseholdResourceService]:
    if dependencies.v2_user_household_service_factory is not None:
        return dependencies.v2_user_household_service_factory
    return _default_v2_user_household_service_factory


def build_v2_user_household_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build user association routes without opening a connection.

    Authentication is a router-level dependency, so a missing or invalid
    credential is rejected before query or body validation.
    """
    require_user = dependencies.require_user
    router = APIRouter(
        prefix="/v2",
        responses=USER_HOUSEHOLD_ERROR_RESPONSES,
        dependencies=[
            Depends(require_user),
            Depends(enforce_user_write_request_size),
        ],
    )
    service_factory = _service_factory(dependencies)

    @router.post(
        "/user-households",
        response_model=UserHouseholdDetailResponse,
        status_code=201,
        summary="Save a household for the current user",
        description=(
            "Requires a bearer access token or the PolicyEngine-Unauthenticated-User "
            "header; the owner is taken from that credential. "
            "Accepts legacy_household_id (a v1 household, checked in the v1 "
            "database) or household_id (a v2 household)."
        ),
    )
    def create_user_household(
        body: UserHouseholdCreateRequest,
        query: UserHouseholdCreateQueryDependency,
        principal: AccountPrincipal = Depends(require_user),
    ) -> UserHouseholdDetailResponse | JSONResponse:
        if body.country_id != query.country_id:
            return v2_error_response(400, "Body country_id must match query country_id")

        def create() -> UserHouseholdDetailResponse:
            item = service_factory().create_user_household(
                principal=principal,
                association_input=body,
            )
            return UserHouseholdDetailResponse(
                result=UserHouseholdDetailResult(item=UserHouseholdItem.from_read(item))
            )

        return user_resource_operation(create)

    @router.get(
        "/user-households/{association_id}",
        response_model=UserHouseholdDetailResponse,
        summary="Read one of the current user's saved households",
    )
    def get_user_household(
        association_id: UUID,
        query: UserHouseholdDetailQueryDependency,
        principal: AccountPrincipal = Depends(require_user),
    ) -> UserHouseholdDetailResponse | JSONResponse:
        def read() -> UserHouseholdDetailResponse:
            item = service_factory().get_user_household(
                principal=principal,
                country_id=query.country_id,
                association_id=association_id,
            )
            return UserHouseholdDetailResponse(
                result=UserHouseholdDetailResult(item=UserHouseholdItem.from_read(item))
            )

        return user_resource_operation(read)

    @router.get(
        "/user-households",
        response_model=UserHouseholdPageResponse,
        summary="List the current user's saved households",
    )
    def get_user_households(
        query: UserHouseholdCollectionQueryDependency,
        principal: AccountPrincipal = Depends(require_user),
    ) -> UserHouseholdPageResponse | JSONResponse:
        def read() -> UserHouseholdPageResponse:
            page = service_factory().list_user_households(
                principal=principal,
                country_id=query.country_id,
                household_id=query.household_id,
                legacy_household_id=query.legacy_household_id,
                offset=query.offset,
                limit=query.limit,
            )
            return UserHouseholdPageResponse(
                result=UserHouseholdPageResult.from_page(page)
            )

        return user_resource_operation(read)

    @router.patch(
        "/user-households/{association_id}",
        response_model=UserHouseholdDetailResponse,
        summary="Update or repoint one of the current user's saved households",
        description=(
            "Changing legacy_household_id repoints the row and re-resolves "
            "household_id from the Stage 11 copy mapping, or clears it."
        ),
    )
    def patch_user_household_route(
        association_id: UUID,
        body: UserHouseholdPatchRequest,
        query: UserHouseholdUpdateQueryDependency,
        principal: AccountPrincipal = Depends(require_user),
    ) -> UserHouseholdDetailResponse | JSONResponse:
        def patch() -> UserHouseholdDetailResponse:
            item = service_factory().patch_user_household(
                principal=principal,
                country_id=query.country_id,
                association_id=association_id,
                association_input=body,
            )
            return UserHouseholdDetailResponse(
                result=UserHouseholdDetailResult(item=UserHouseholdItem.from_read(item))
            )

        return user_resource_operation(patch)

    @router.delete(
        "/user-households/{association_id}",
        response_model=None,
        status_code=204,
        response_class=Response,
        summary="Delete one of the current user's saved households",
    )
    def delete_user_household_route(
        association_id: UUID,
        query: UserHouseholdDeleteQueryDependency,
        principal: AccountPrincipal = Depends(require_user),
    ) -> Response | JSONResponse:
        def delete() -> Response:
            service_factory().delete_user_household(
                principal=principal,
                country_id=query.country_id,
                association_id=association_id,
            )
            return Response(status_code=204)

        return user_resource_operation(delete)

    return router
