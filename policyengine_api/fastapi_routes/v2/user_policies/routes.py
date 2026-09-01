"""Native FastAPI routes for mutable v2 user-policy associations."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse, Response

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.v2.user_policies.request_models import (
    UserPolicyCreateRequest,
    UserPolicyPatchRequest,
)
from policyengine_api.fastapi_routes.v2.user_policies.response_models import (
    USER_POLICY_ERROR_RESPONSES,
    UserPolicyDetailResponse,
    UserPolicyDetailResult,
    UserPolicyErrorResponse,
    UserPolicyItem,
    UserPolicyPageResponse,
    UserPolicyPageResult,
)
from policyengine_api.data.v2.user_policies.queries import (
    UserPolicyNotFoundError,
)
from policyengine_api.data.v2.user_policies.persistence import (
    AssociationCountryConflictError,
    AssociationPolicyNotFoundError,
    AssociationUserNotFoundError,
)
from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2UserPolicyResourceService,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.query_parameters import (
    CountryQuery,
    UserPolicyCollectionQuery,
)


def user_policy_error_response(status_code: int, message: str) -> JSONResponse:
    error = UserPolicyErrorResponse(message=message)
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json"),
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


OperationT = TypeVar("OperationT")


def _association_operation(
    operation: Callable[[], OperationT],
) -> OperationT | JSONResponse:
    try:
        return operation()
    except AssociationCountryConflictError as error:
        return user_policy_error_response(400, str(error))
    except (
        AssociationPolicyNotFoundError,
        AssociationUserNotFoundError,
        UserPolicyNotFoundError,
    ) as error:
        return user_policy_error_response(404, str(error))
    except (V2ConfigurationError, SQLAlchemyError):
        return user_policy_error_response(
            503,
            "V2 association persistence is unavailable",
        )
    except Exception:  # noqa: BLE001 - return a secret-safe typed error
        return user_policy_error_response(500, "V2 association operation failed")


def build_v2_user_policy_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build native association routes without opening a database connection."""

    router = APIRouter(prefix="/v2", responses=USER_POLICY_ERROR_RESPONSES)
    country_query = query_dependency(CountryQuery)
    collection_query = query_dependency(UserPolicyCollectionQuery)
    service_factory = _service_factory(dependencies)

    @router.post(
        "/user-policies",
        response_model=UserPolicyDetailResponse,
        status_code=201,
        summary="Create a user-policy association",
        description=(
            "Creates a saved association for an existing v2 user UUID. The "
            "UUID identifies a database row; this operation does not prove "
            "that the caller controls that user and performs no authentication "
            "or authorization check."
        ),
    )
    def create_user_policy(
        body: UserPolicyCreateRequest,
        query: CountryQuery = Depends(country_query),
    ) -> UserPolicyDetailResponse | JSONResponse:
        if body.country_id != query.country_id:
            return user_policy_error_response(
                400,
                "Body country_id must match query country_id",
            )

        def create() -> UserPolicyDetailResponse:
            item = service_factory().create_user_policy(body)
            return UserPolicyDetailResponse(
                result=UserPolicyDetailResult(item=UserPolicyItem.from_read(item))
            )

        return _association_operation(create)

    @router.get(
        "/user-policies/{association_id}",
        response_model=UserPolicyDetailResponse,
        summary="Read one user-policy association",
    )
    def get_user_policy(
        association_id: UUID,
        query: CountryQuery = Depends(country_query),
    ) -> UserPolicyDetailResponse | JSONResponse:
        def read() -> UserPolicyDetailResponse:
            item = service_factory().get_user_policy(
                country_id=query.country_id,
                association_id=association_id,
            )
            return UserPolicyDetailResponse(
                result=UserPolicyDetailResult(item=UserPolicyItem.from_read(item))
            )

        return _association_operation(read)

    @router.get(
        "/user-policies",
        response_model=UserPolicyPageResponse,
        summary="List user-policy associations",
        description=(
            "Filters by a v2 user UUID. A match is not proof of caller control "
            "and is not an authentication or authorization decision."
        ),
    )
    def get_user_policies(
        query: UserPolicyCollectionQuery = Depends(collection_query),
    ) -> UserPolicyPageResponse | JSONResponse:
        def read() -> UserPolicyPageResponse:
            page = service_factory().list_user_policies(
                country_id=query.country_id,
                user_id=query.user_id,
                policy_id=query.policy_id,
                offset=query.offset,
                limit=query.limit,
            )
            return UserPolicyPageResponse(result=UserPolicyPageResult.from_page(page))

        return _association_operation(read)

    @router.patch(
        "/user-policies/{association_id}",
        response_model=UserPolicyDetailResponse,
        summary="Update association presentation fields",
    )
    def patch_user_policy_route(
        association_id: UUID,
        body: UserPolicyPatchRequest,
        query: CountryQuery = Depends(country_query),
    ) -> UserPolicyDetailResponse | JSONResponse:
        def patch() -> UserPolicyDetailResponse:
            item = service_factory().patch_user_policy(
                country_id=query.country_id,
                association_id=association_id,
                command=body,
            )
            return UserPolicyDetailResponse(
                result=UserPolicyDetailResult(item=UserPolicyItem.from_read(item))
            )

        return _association_operation(patch)

    @router.delete(
        "/user-policies/{association_id}",
        response_model=None,
        status_code=204,
        response_class=Response,
        summary="Delete one user-policy association",
    )
    def delete_user_policy_route(
        association_id: UUID,
        query: CountryQuery = Depends(country_query),
    ) -> Response | JSONResponse:
        def delete() -> Response:
            service_factory().delete_user_policy(
                country_id=query.country_id,
                association_id=association_id,
            )
            return Response(status_code=204)

        return _association_operation(delete)

    return router
