"""Native FastAPI routes for mutable v2 user-household associations."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.responses import JSONResponse, Response

from policyengine_api.data.v2.settings import V2ConfigurationError
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
from policyengine_api.query_parameters import (
    UserHouseholdCollectionQuery,
    UserHouseholdCreateQuery,
    UserHouseholdDeleteQuery,
    UserHouseholdDetailQuery,
    UserHouseholdUpdateQuery,
)
from policyengine_api.services.v2.user_households.validators import (
    AssociationCountryConflictError,
    AssociationHouseholdNotFoundError,
    AssociationUserNotFoundError,
    UserHouseholdNotFoundError,
)


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2UserHouseholdResourceService]:
    if dependencies.v2_user_household_service_factory is not None:
        return dependencies.v2_user_household_service_factory
    from policyengine_api.fastapi_routes.dependencies import (
        _default_v2_user_household_service_factory,
    )

    return _default_v2_user_household_service_factory


OperationT = TypeVar("OperationT")


def _association_operation(
    operation: Callable[[], OperationT],
) -> OperationT | JSONResponse:
    try:
        return operation()
    except AssociationCountryConflictError as error:
        return v2_error_response(400, str(error))
    except (
        AssociationHouseholdNotFoundError,
        AssociationUserNotFoundError,
        UserHouseholdNotFoundError,
    ) as error:
        return v2_error_response(404, str(error))
    except IntegrityError:
        return v2_error_response(
            409, "User-household association conflicts with storage"
        )
    except (V2ConfigurationError, SQLAlchemyError):
        return v2_error_response(503, "V2 association persistence is unavailable")
    except Exception:  # noqa: BLE001 - return a secret-safe typed error
        return v2_error_response(500, "V2 association operation failed")


def build_v2_user_household_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build native association routes without opening a database connection."""

    router = APIRouter(prefix="/v2", responses=USER_HOUSEHOLD_ERROR_RESPONSES)
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
        summary="Create a user-household association",
        description=(
            "Creates a saved association for an existing v2 user UUID. The UUID "
            "identifies a database row; this operation does not prove that the "
            "caller controls that user and performs no authentication or "
            "authorization check."
        ),
    )
    def create_user_household(
        body: UserHouseholdCreateRequest,
        query: UserHouseholdCreateQuery = Depends(create_query),
    ) -> UserHouseholdDetailResponse | JSONResponse:
        if body.country_id != query.country_id:
            return v2_error_response(400, "Body country_id must match query country_id")

        def create() -> UserHouseholdDetailResponse:
            item = service_factory().create_user_household(body)
            return UserHouseholdDetailResponse(
                result=UserHouseholdDetailResult(item=UserHouseholdItem.from_read(item))
            )

        return _association_operation(create)

    @router.get(
        "/user-households/{association_id}",
        response_model=UserHouseholdDetailResponse,
        summary="Read one user-household association",
    )
    def get_user_household(
        association_id: UUID,
        query: UserHouseholdDetailQuery = Depends(detail_query),
    ) -> UserHouseholdDetailResponse | JSONResponse:
        def read() -> UserHouseholdDetailResponse:
            item = service_factory().get_user_household(
                country_id=query.country_id,
                association_id=association_id,
            )
            return UserHouseholdDetailResponse(
                result=UserHouseholdDetailResult(item=UserHouseholdItem.from_read(item))
            )

        return _association_operation(read)

    @router.get(
        "/user-households",
        response_model=UserHouseholdPageResponse,
        summary="List user-household associations",
        description=(
            "Filters by a v2 user UUID. A match is not proof of caller control "
            "and is not an authentication or authorization decision."
        ),
    )
    def get_user_households(
        query: UserHouseholdCollectionQuery = Depends(collection_query),
    ) -> UserHouseholdPageResponse | JSONResponse:
        def read() -> UserHouseholdPageResponse:
            page = service_factory().list_user_households(
                country_id=query.country_id,
                user_id=query.user_id,
                household_id=query.household_id,
                offset=query.offset,
                limit=query.limit,
            )
            return UserHouseholdPageResponse(
                result=UserHouseholdPageResult.from_page(page)
            )

        return _association_operation(read)

    @router.patch(
        "/user-households/{association_id}",
        response_model=UserHouseholdDetailResponse,
        summary="Update or reassign a user-household association",
    )
    def patch_user_household_route(
        association_id: UUID,
        body: UserHouseholdPatchRequest,
        query: UserHouseholdUpdateQuery = Depends(update_query),
    ) -> UserHouseholdDetailResponse | JSONResponse:
        def patch() -> UserHouseholdDetailResponse:
            item = service_factory().patch_user_household(
                country_id=query.country_id,
                association_id=association_id,
                association_input=body,
            )
            return UserHouseholdDetailResponse(
                result=UserHouseholdDetailResult(item=UserHouseholdItem.from_read(item))
            )

        return _association_operation(patch)

    @router.delete(
        "/user-households/{association_id}",
        response_model=None,
        status_code=204,
        response_class=Response,
        summary="Delete one user-household association",
    )
    def delete_user_household_route(
        association_id: UUID,
        query: UserHouseholdDeleteQuery = Depends(delete_query),
    ) -> Response | JSONResponse:
        def delete() -> Response:
            service_factory().delete_user_household(
                country_id=query.country_id,
                association_id=association_id,
            )
            return Response(status_code=204)

        return _association_operation(delete)

    return router
