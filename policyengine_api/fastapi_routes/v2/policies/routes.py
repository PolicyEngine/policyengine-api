"""Native FastAPI routes for immutable v2 policies."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
)
from policyengine_api.fastapi_routes.v2.policies.request_models import (
    MAXIMUM_POLICY_REQUEST_BYTES,
    PolicyCreateRequest,
)
from policyengine_api.fastapi_routes.v2.policies.response_models import (
    POLICY_ERROR_RESPONSES,
    PolicyDetailResponse,
    PolicyDetailResult,
    PolicyErrorResponse,
    PolicyItem,
    PolicyPageResponse,
    PolicyPageResult,
)
from policyengine_api.services.v2.policies.types import NativePolicyCreationInput
from policyengine_api.services.v2.policies.validators import (
    PolicyCatalogValidationError,
    PolicyContentHashCollisionError,
    PolicyCreationIntegrityError,
    PolicyNotFoundError,
)
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2PolicyResourceService,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.query_parameters import (
    PolicyCollectionQuery,
    PolicyCreateQuery,
    PolicyDetailQuery,
)


class PolicyRequestTooLargeError(ValueError):
    """Raised before persistence when a native policy body exceeds 1 MiB."""


async def enforce_policy_request_size(request: Request) -> None:
    """Bound both declared and actual request bytes before service creation."""

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise PolicyRequestTooLargeError(
                "Policy request Content-Length is invalid"
            ) from error
        if declared_length > MAXIMUM_POLICY_REQUEST_BYTES:
            raise PolicyRequestTooLargeError("Policy request body exceeds 1 MiB")
    if len(await request.body()) > MAXIMUM_POLICY_REQUEST_BYTES:
        raise PolicyRequestTooLargeError("Policy request body exceeds 1 MiB")


def policy_error_response(status_code: int, message: str) -> JSONResponse:
    error = PolicyErrorResponse(message=message)
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json"),
    )


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2PolicyResourceService]:
    if dependencies.v2_policy_service_factory is not None:
        return dependencies.v2_policy_service_factory
    from policyengine_api.fastapi_routes.dependencies import (
        _default_v2_policy_service_factory,
    )

    return _default_v2_policy_service_factory


OperationT = TypeVar("OperationT")


def _policy_operation(
    operation: Callable[[], OperationT],
) -> OperationT | JSONResponse:
    try:
        return operation()
    except PolicyCatalogValidationError as error:
        return policy_error_response(400, str(error))
    except (MetadataCatalogVersionNotFoundError, PolicyNotFoundError) as error:
        return policy_error_response(404, str(error))
    except PolicyContentHashCollisionError:
        return policy_error_response(409, "Policy content hash conflicts with storage")
    except PolicyCreationIntegrityError:
        return policy_error_response(500, "Stored policy integrity failed")
    except (V2ConfigurationError, MetadataCatalogUnavailableError, SQLAlchemyError):
        return policy_error_response(503, "V2 policy persistence is unavailable")
    except Exception:  # noqa: BLE001 - route must return a secret-safe typed error
        return policy_error_response(500, "V2 policy operation failed")


def build_v2_policy_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build native policy routes without opening a database connection."""

    router = APIRouter(prefix="/v2", responses=POLICY_ERROR_RESPONSES)
    create_query = query_dependency(PolicyCreateQuery)
    detail_query = query_dependency(PolicyDetailQuery)
    collection_query = query_dependency(PolicyCollectionQuery)
    service_factory = _service_factory(dependencies)

    @router.post(
        "/policies",
        response_model=PolicyDetailResponse,
        status_code=201,
        responses={
            200: {
                "model": PolicyDetailResponse,
                "description": "Equivalent immutable content already exists.",
            }
        },
        summary="Create or find an immutable policy",
    )
    def create_policy(
        body: PolicyCreateRequest,
        query: PolicyCreateQuery = Depends(create_query),
        _size: None = Depends(enforce_policy_request_size),
    ) -> PolicyDetailResponse | JSONResponse:
        if body.country_id != query.country_id:
            return policy_error_response(
                400,
                "Body country_id must match query country_id",
            )

        def create() -> PolicyDetailResponse | JSONResponse:
            result = service_factory().create_policy(
                NativePolicyCreationInput(
                    **body.model_dump(),
                    policyengine_version=query.policyengine_version,
                )
            )
            response = PolicyDetailResponse(
                result=PolicyDetailResult(item=PolicyItem.from_read(result.item))
            )
            if result.created:
                return response
            return JSONResponse(
                status_code=200,
                content=response.model_dump(mode="json"),
            )

        return _policy_operation(create)

    @router.get(
        "/policies/{policy_id}",
        response_model=PolicyDetailResponse,
        summary="Read one immutable policy",
    )
    def get_policy(
        policy_id: UUID,
        query: PolicyDetailQuery = Depends(detail_query),
    ) -> PolicyDetailResponse | JSONResponse:
        def read() -> PolicyDetailResponse:
            item = service_factory().get_policy(
                country_id=query.country_id,
                policy_id=policy_id,
            )
            return PolicyDetailResponse(
                result=PolicyDetailResult(item=PolicyItem.from_read(item))
            )

        return _policy_operation(read)

    @router.get(
        "/policies",
        response_model=PolicyPageResponse,
        summary="List immutable policies",
    )
    def get_policies(
        query: PolicyCollectionQuery = Depends(collection_query),
    ) -> PolicyPageResponse | JSONResponse:
        def read() -> PolicyPageResponse:
            page = service_factory().list_policies(
                country_id=query.country_id,
                tax_benefit_model_id=query.tax_benefit_model_id,
                offset=query.offset,
                limit=query.limit,
            )
            return PolicyPageResponse(result=PolicyPageResult.from_page(page))

        return _policy_operation(read)

    return router
