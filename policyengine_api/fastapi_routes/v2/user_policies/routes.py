"""Native FastAPI routes for v2 user-policy associations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse, Response

from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.errors import v2_error_response
from policyengine_api.fastapi_routes.v2.user_policies.request_models import (
    UserPolicyCreateRequest,
    UserPolicyPatchRequest,
)
from policyengine_api.fastapi_routes.v2.user_policies.response_models import (
    USER_POLICY_ERROR_RESPONSES,
    UserPolicyDetailResponse,
    UserPolicyDetailResult,
    UserPolicyItem,
    UserPolicyPageResponse,
    UserPolicyPageResult,
)
from policyengine_api.fastapi_routes.v2.user_resources import (
    enforce_user_write_request_size,
    user_resource_operation,
)
from policyengine_api.query_parameters import (
    CountryQuery,
    UserPolicyCollectionQuery,
)
from policyengine_api.services.v2.identity.types import AccountPrincipal

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
        V2UserPolicyResourceService,
    )


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2UserPolicyResourceService]:
    if dependencies.v2_user_policy_service_factory is not None:
        return dependencies.v2_user_policy_service_factory
    from policyengine_api.fastapi_routes.dependencies import (
        _default_v2_user_policy_service_factory,
    )

    return _default_v2_user_policy_service_factory


def build_v2_user_policy_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build user association routes without opening a connection.

    Authentication is a router-level dependency, so a missing or invalid
    credential is rejected before query or body validation.
    """

    require_user = dependencies.require_user
    router = APIRouter(
        prefix="/v2",
        responses=USER_POLICY_ERROR_RESPONSES,
        dependencies=[
            Depends(require_user),
            Depends(enforce_user_write_request_size),
        ],
    )
    country_query = query_dependency(CountryQuery)
    collection_query = query_dependency(UserPolicyCollectionQuery)
    service_factory = _service_factory(dependencies)

    @router.post(
        "/user-policies",
        response_model=UserPolicyDetailResponse,
        status_code=201,
        summary="Save a policy for the current user",
        description=(
            "Requires a bearer access token or the PolicyEngine-Unauthenticated-User "
            "header; the owner is taken from that credential. "
            "Accepts legacy_policy_id (a v1 policy, checked in the v1 database) "
            "or policy_id (a v2 policy). When only legacy_policy_id is supplied, "
            "policy_id is filled from the Stage 10 mirror mapping when one exists."
        ),
    )
    def create_user_policy(
        body: UserPolicyCreateRequest,
        query: CountryQuery = Depends(country_query),
        principal: AccountPrincipal = Depends(require_user),
    ) -> UserPolicyDetailResponse | JSONResponse:
        if body.country_id != query.country_id:
            return v2_error_response(
                400,
                "Body country_id must match query country_id",
            )

        def create() -> UserPolicyDetailResponse:
            item = service_factory().create_user_policy(
                principal=principal,
                association_input=body,
            )
            return UserPolicyDetailResponse(
                result=UserPolicyDetailResult(item=UserPolicyItem.from_read(item))
            )

        return user_resource_operation(create)

    @router.get(
        "/user-policies/{association_id}",
        response_model=UserPolicyDetailResponse,
        summary="Read one of the current user's saved policies",
    )
    def get_user_policy(
        association_id: UUID,
        query: CountryQuery = Depends(country_query),
        principal: AccountPrincipal = Depends(require_user),
    ) -> UserPolicyDetailResponse | JSONResponse:
        def read() -> UserPolicyDetailResponse:
            item = service_factory().get_user_policy(
                principal=principal,
                country_id=query.country_id,
                association_id=association_id,
            )
            return UserPolicyDetailResponse(
                result=UserPolicyDetailResult(item=UserPolicyItem.from_read(item))
            )

        return user_resource_operation(read)

    @router.get(
        "/user-policies",
        response_model=UserPolicyPageResponse,
        summary="List the current user's saved policies",
    )
    def get_user_policies(
        query: UserPolicyCollectionQuery = Depends(collection_query),
        principal: AccountPrincipal = Depends(require_user),
    ) -> UserPolicyPageResponse | JSONResponse:
        def read() -> UserPolicyPageResponse:
            page = service_factory().list_user_policies(
                principal=principal,
                country_id=query.country_id,
                policy_id=query.policy_id,
                legacy_policy_id=query.legacy_policy_id,
                offset=query.offset,
                limit=query.limit,
            )
            return UserPolicyPageResponse(result=UserPolicyPageResult.from_page(page))

        return user_resource_operation(read)

    @router.patch(
        "/user-policies/{association_id}",
        response_model=UserPolicyDetailResponse,
        summary="Update or repoint one of the current user's saved policies",
        description=(
            "Changing legacy_policy_id repoints the row and re-resolves policy_id "
            "from the Stage 10 mirror mapping, or clears it. Rows maintained by "
            "the v1 saved-policy mirror return 409."
        ),
    )
    def patch_user_policy_route(
        association_id: UUID,
        body: UserPolicyPatchRequest,
        query: CountryQuery = Depends(country_query),
        principal: AccountPrincipal = Depends(require_user),
    ) -> UserPolicyDetailResponse | JSONResponse:
        def patch() -> UserPolicyDetailResponse:
            item = service_factory().patch_user_policy(
                principal=principal,
                country_id=query.country_id,
                association_id=association_id,
                association_input=body,
            )
            return UserPolicyDetailResponse(
                result=UserPolicyDetailResult(item=UserPolicyItem.from_read(item))
            )

        return user_resource_operation(patch)

    @router.delete(
        "/user-policies/{association_id}",
        response_model=None,
        status_code=204,
        response_class=Response,
        summary="Delete one of the current user's saved policies",
    )
    def delete_user_policy_route(
        association_id: UUID,
        query: CountryQuery = Depends(country_query),
        principal: AccountPrincipal = Depends(require_user),
    ) -> Response | JSONResponse:
        def delete() -> Response:
            service_factory().delete_user_policy(
                principal=principal,
                country_id=query.country_id,
                association_id=association_id,
            )
            return Response(status_code=204)

        return user_resource_operation(delete)

    return router
