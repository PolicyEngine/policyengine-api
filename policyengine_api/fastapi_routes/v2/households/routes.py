"""Native FastAPI routes for immutable v2 households."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2HouseholdResourceService,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.errors import (
    V2RequestTooLargeError,
    v2_error_response,
)
from policyengine_api.fastapi_routes.v2.households.request_models import (
    MAXIMUM_HOUSEHOLD_REQUEST_BYTES,
    HouseholdCreateRequest,
)
from policyengine_api.fastapi_routes.v2.households.response_models import (
    HOUSEHOLD_ERROR_RESPONSES,
    HouseholdDetailResponse,
    HouseholdDetailResult,
    HouseholdItem,
    HouseholdPageResponse,
    HouseholdPageResult,
)
from policyengine_api.query_parameters import (
    HouseholdCollectionQuery,
    HouseholdCreateQuery,
    HouseholdDetailQuery,
)
from policyengine_api.services.v2.households.validators import (
    HouseholdContentHashCollisionError,
    HouseholdCreationIntegrityError,
    HouseholdNotFoundError,
    HouseholdValidationError,
)


async def enforce_household_request_size(request: Request) -> None:
    """Reject declared or actual request bodies larger than 1 MiB."""

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise V2RequestTooLargeError(
                "Household request Content-Length is invalid"
            ) from error
        if declared_length > MAXIMUM_HOUSEHOLD_REQUEST_BYTES:
            raise V2RequestTooLargeError("Household request body exceeds 1 MiB")
    if len(await request.body()) > MAXIMUM_HOUSEHOLD_REQUEST_BYTES:
        raise V2RequestTooLargeError("Household request body exceeds 1 MiB")


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2HouseholdResourceService]:
    if dependencies.v2_household_service_factory is not None:
        return dependencies.v2_household_service_factory
    from policyengine_api.fastapi_routes.dependencies import (
        _default_v2_household_service_factory,
    )

    return _default_v2_household_service_factory


OperationT = TypeVar("OperationT")


def _household_operation(
    operation: Callable[[], OperationT],
) -> OperationT | JSONResponse:
    try:
        return operation()
    except HouseholdValidationError as error:
        return v2_error_response(400, str(error))
    except HouseholdNotFoundError as error:
        return v2_error_response(404, str(error))
    except HouseholdContentHashCollisionError:
        return v2_error_response(409, "Household content hash conflicts with storage")
    except HouseholdCreationIntegrityError:
        return v2_error_response(500, "Stored household integrity failed")
    except (V2ConfigurationError, SQLAlchemyError):
        return v2_error_response(503, "V2 household persistence is unavailable")
    except Exception:  # noqa: BLE001 - return a secret-safe typed error
        return v2_error_response(500, "V2 household operation failed")


def build_v2_household_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build native household routes without opening a database connection."""

    router = APIRouter(prefix="/v2", responses=HOUSEHOLD_ERROR_RESPONSES)
    create_query = query_dependency(HouseholdCreateQuery)
    detail_query = query_dependency(HouseholdDetailQuery)
    collection_query = query_dependency(HouseholdCollectionQuery)
    service_factory = _service_factory(dependencies)

    @router.post(
        "/households",
        response_model=HouseholdDetailResponse,
        status_code=201,
        responses={
            200: {
                "model": HouseholdDetailResponse,
                "description": "Equivalent immutable content already exists.",
            }
        },
        summary="Create or find an immutable household",
    )
    def create_household(
        body: HouseholdCreateRequest,
        query: HouseholdCreateQuery = Depends(create_query),
        _size: None = Depends(enforce_household_request_size),
    ) -> HouseholdDetailResponse | JSONResponse:
        if body.country_id != query.country_id:
            return v2_error_response(400, "Body country_id must match query country_id")

        def create() -> HouseholdDetailResponse | JSONResponse:
            result = service_factory().create_household(body.to_service_input())
            response = HouseholdDetailResponse(
                result=HouseholdDetailResult(item=HouseholdItem.from_read(result.item))
            )
            if result.created:
                return response
            return JSONResponse(
                status_code=200,
                content=response.model_dump(mode="json"),
            )

        return _household_operation(create)

    @router.get(
        "/households/{household_id}",
        response_model=HouseholdDetailResponse,
        summary="Read one immutable household",
    )
    def get_household(
        household_id: UUID,
        query: HouseholdDetailQuery = Depends(detail_query),
    ) -> HouseholdDetailResponse | JSONResponse:
        def read() -> HouseholdDetailResponse:
            item = service_factory().get_household(
                country_id=query.country_id,
                household_id=household_id,
            )
            return HouseholdDetailResponse(
                result=HouseholdDetailResult(item=HouseholdItem.from_read(item))
            )

        return _household_operation(read)

    @router.get(
        "/households",
        response_model=HouseholdPageResponse,
        summary="List immutable households",
    )
    def get_households(
        query: HouseholdCollectionQuery = Depends(collection_query),
    ) -> HouseholdPageResponse | JSONResponse:
        def read() -> HouseholdPageResponse:
            page = service_factory().list_households(
                country_id=query.country_id,
                default_year=query.default_year,
                offset=query.offset,
                limit=query.limit,
            )
            return HouseholdPageResponse(result=HouseholdPageResult.from_page(page))

        return _household_operation(read)

    return router
