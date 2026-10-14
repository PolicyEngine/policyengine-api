"""Native FastAPI routes for v2 user-simulation associations."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse, Response

from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2UserSimulationResourceService,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.errors import v2_error_response
from policyengine_api.fastapi_routes.v2.user_resources import (
    USER_RESOURCE_ERROR_RESPONSES,
    enforce_user_write_request_size,
    user_resource_operation,
)
from policyengine_api.fastapi_routes.v2.user_simulations.request_models import (
    UserSimulationCreateRequest,
    UserSimulationPatchRequest,
)
from policyengine_api.fastapi_routes.v2.user_simulations.response_models import (
    UserSimulationDetailResponse,
    UserSimulationDetailResult,
    UserSimulationItem,
    UserSimulationPageResponse,
    UserSimulationPageResult,
)
from policyengine_api.query_parameters import (
    CountryQuery,
    UserSimulationCollectionQuery,
)
from policyengine_api.services.v2.identity.types import AccountPrincipal


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2UserSimulationResourceService]:
    if dependencies.v2_user_simulation_service_factory is not None:
        return dependencies.v2_user_simulation_service_factory
    from policyengine_api.fastapi_routes.dependencies import (
        _default_v2_user_simulation_service_factory,
    )

    return _default_v2_user_simulation_service_factory


def build_v2_user_simulation_router(
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
    country_query = query_dependency(CountryQuery)
    collection_query = query_dependency(UserSimulationCollectionQuery)
    service_factory = _service_factory(dependencies)

    @router.post(
        "/user-simulations",
        response_model=UserSimulationDetailResponse,
        status_code=201,
        summary="Save a v1 simulation for the current user",
        description=(
            "Requires a bearer access token or the PolicyEngine-Unauthenticated-User "
            "header; the owner is taken from that credential. "
            "Stage 12A accepts legacy_simulation_id only, checked in the v1 "
            "database."
        ),
    )
    def create_user_simulation(
        body: UserSimulationCreateRequest,
        query: CountryQuery = Depends(country_query),
        principal: AccountPrincipal = Depends(require_user),
    ) -> UserSimulationDetailResponse | JSONResponse:
        if body.country_id != query.country_id:
            return v2_error_response(400, "Body country_id must match query country_id")

        def create() -> UserSimulationDetailResponse:
            item = service_factory().create_user_simulation(
                principal=principal,
                association_input=body,
            )
            return UserSimulationDetailResponse(
                result=UserSimulationDetailResult(
                    item=UserSimulationItem.from_read(item)
                )
            )

        return user_resource_operation(create)

    @router.get(
        "/user-simulations/{association_id}",
        response_model=UserSimulationDetailResponse,
        summary="Read one of the current user's saved simulations",
    )
    def get_user_simulation(
        association_id: UUID,
        query: CountryQuery = Depends(country_query),
        principal: AccountPrincipal = Depends(require_user),
    ) -> UserSimulationDetailResponse | JSONResponse:
        def read() -> UserSimulationDetailResponse:
            item = service_factory().get_user_simulation(
                principal=principal,
                country_id=query.country_id,
                association_id=association_id,
            )
            return UserSimulationDetailResponse(
                result=UserSimulationDetailResult(
                    item=UserSimulationItem.from_read(item)
                )
            )

        return user_resource_operation(read)

    @router.get(
        "/user-simulations",
        response_model=UserSimulationPageResponse,
        summary="List the current user's saved simulations",
    )
    def get_user_simulations(
        query: UserSimulationCollectionQuery = Depends(collection_query),
        principal: AccountPrincipal = Depends(require_user),
    ) -> UserSimulationPageResponse | JSONResponse:
        def read() -> UserSimulationPageResponse:
            page = service_factory().list_user_simulations(
                principal=principal,
                country_id=query.country_id,
                legacy_simulation_id=query.legacy_simulation_id,
                offset=query.offset,
                limit=query.limit,
            )
            return UserSimulationPageResponse(
                result=UserSimulationPageResult.from_page(page)
            )

        return user_resource_operation(read)

    @router.patch(
        "/user-simulations/{association_id}",
        response_model=UserSimulationDetailResponse,
        summary="Update or repoint one of the current user's saved simulations",
    )
    def patch_user_simulation_route(
        association_id: UUID,
        body: UserSimulationPatchRequest,
        query: CountryQuery = Depends(country_query),
        principal: AccountPrincipal = Depends(require_user),
    ) -> UserSimulationDetailResponse | JSONResponse:
        def patch() -> UserSimulationDetailResponse:
            item = service_factory().patch_user_simulation(
                principal=principal,
                country_id=query.country_id,
                association_id=association_id,
                association_input=body,
            )
            return UserSimulationDetailResponse(
                result=UserSimulationDetailResult(
                    item=UserSimulationItem.from_read(item)
                )
            )

        return user_resource_operation(patch)

    @router.delete(
        "/user-simulations/{association_id}",
        response_model=None,
        status_code=204,
        response_class=Response,
        summary="Delete one of the current user's saved simulations",
    )
    def delete_user_simulation_route(
        association_id: UUID,
        query: CountryQuery = Depends(country_query),
        principal: AccountPrincipal = Depends(require_user),
    ) -> Response | JSONResponse:
        def delete() -> Response:
            service_factory().delete_user_simulation(
                principal=principal,
                country_id=query.country_id,
                association_id=association_id,
            )
            return Response(status_code=204)

        return user_resource_operation(delete)

    return router
