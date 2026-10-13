"""Native FastAPI routes for signed-in v2 user-household associations."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse, Response

from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2UserHouseholdResourceService,
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
from policyengine_api.services.v2.identity.types import UserPrincipal


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2UserHouseholdResourceService]:
    if dependencies.v2_user_household_service_factory is not None:
        return dependencies.v2_user_household_service_factory
    from policyengine_api.fastapi_routes.dependencies import (
        _default_v2_user_household_service_factory,
    )

    return _default_v2_user_household_service_factory


def build_v2_user_household_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build signed-in association routes without opening a connection.

    Authentication is a router-level dependency, so a missing or invalid
    token is rejected before query or body validation.
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
    create_query = query_dependency(UserHouseholdCreateQuery)
    detail_query = query_dependency(UserHouseholdDetailQuery)
    collection_query = query_dependency(UserHouseholdCollectionQuery)
    update_query = query_dependency(UserHouseholdUpdateQuery)
    delete_query = query_dependency(UserHouseholdDeleteQuery)
    service_factory = _service_factory(dependencies)

    @router.post(
        "/user-households",
        response_model=UserHouseholdDetailResponse,
        status_code=201,
        summary="Save a household for the signed-in user",
        description=(
            "Requires a user bearer token; the owner is taken from the token. "
            "Accepts legacy_household_id (a v1 household, checked in the v1 "
            "database) or household_id (a v2 household)."
        ),
    )
    def create_user_household(
        body: UserHouseholdCreateRequest,
        query: UserHouseholdCreateQuery = Depends(create_query),
        principal: UserPrincipal = Depends(require_user),
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
        summary="Read one of the signed-in user's saved households",
    )
    def get_user_household(
        association_id: UUID,
        query: UserHouseholdDetailQuery = Depends(detail_query),
        principal: UserPrincipal = Depends(require_user),
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
        summary="List the signed-in user's saved households",
    )
    def get_user_households(
        query: UserHouseholdCollectionQuery = Depends(collection_query),
        principal: UserPrincipal = Depends(require_user),
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
        summary="Update or repoint one of the signed-in user's saved households",
        description=(
            "Changing legacy_household_id repoints the row and re-resolves "
            "household_id from the Stage 11 copy mapping, or clears it."
        ),
    )
    def patch_user_household_route(
        association_id: UUID,
        body: UserHouseholdPatchRequest,
        query: UserHouseholdUpdateQuery = Depends(update_query),
        principal: UserPrincipal = Depends(require_user),
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
        summary="Delete one of the signed-in user's saved households",
    )
    def delete_user_household_route(
        association_id: UUID,
        query: UserHouseholdDeleteQuery = Depends(delete_query),
        principal: UserPrincipal = Depends(require_user),
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
