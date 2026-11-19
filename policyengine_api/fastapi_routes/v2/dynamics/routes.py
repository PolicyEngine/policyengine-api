"""Native FastAPI routes for immutable v2 dynamics.

A dynamic holds the model's assumptions a simulation applies alongside its
policy. It is created and read as a policy is, needs no user credential (a
user's saved dynamics name it), and is never listed, changed or deleted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse

from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
)
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import (
    _default_v2_dynamic_service_factory,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.dynamics.request_models import (
    MAXIMUM_DYNAMIC_REQUEST_BYTES,
    DynamicCreateRequest,
)
from policyengine_api.fastapi_routes.v2.dynamics.response_models import (
    DYNAMIC_ERROR_RESPONSES,
    DynamicDetailResponse,
    DynamicDetailResult,
    DynamicItem,
    V2PolicyParametersErrorResponse,
)
from policyengine_api.fastapi_routes.v2.errors_support import (
    V2ErrorMapping,
    run_v2_operation,
    v2_error_response,
)
from policyengine_api.fastapi_routes.v2.user_resources_support import (
    request_size_limit,
)
from policyengine_api.query_parameters import DynamicCreateQuery, DynamicDetailQuery
from policyengine_api.services.v2.dynamics.types import NativeDynamicCreationInput
from policyengine_api.services.v2.dynamics.validators import (
    DynamicContentHashCollisionError,
    DynamicCreationIntegrityError,
    DynamicNotFoundError,
    DynamicSetsPolicyParametersError,
    DynamicStorageError,
)
from policyengine_api.services.v2.policies.validators import (
    PolicyCatalogValidationError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
        V2DynamicResourceService,
    )


DynamicCreateQueryDependency = Annotated[
    DynamicCreateQuery, Depends(query_dependency(DynamicCreateQuery))
]
DynamicDetailQueryDependency = Annotated[
    DynamicDetailQuery, Depends(query_dependency(DynamicDetailQuery))
]
enforce_dynamic_request_size = request_size_limit(
    MAXIMUM_DYNAMIC_REQUEST_BYTES, label="1 MiB"
)

OperationT = TypeVar("OperationT")

# Checked in order, so the collision is matched before its integrity base class.
DYNAMIC_ERROR_MAPPINGS = (
    V2ErrorMapping((PolicyCatalogValidationError,), 400),
    V2ErrorMapping((MetadataCatalogVersionNotFoundError, DynamicNotFoundError), 404),
    V2ErrorMapping(
        (DynamicContentHashCollisionError,),
        409,
        "Dynamic content hash conflicts with storage",
    ),
    V2ErrorMapping(
        (DynamicCreationIntegrityError,), 500, "Stored dynamic integrity failed"
    ),
    V2ErrorMapping(
        (V2ConfigurationError, MetadataCatalogUnavailableError, DynamicStorageError),
        503,
        "V2 dynamic persistence is unavailable",
    ),
)


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2DynamicResourceService]:
    if dependencies.v2_dynamic_service_factory is not None:
        return dependencies.v2_dynamic_service_factory
    return _default_v2_dynamic_service_factory


def _policy_parameters_response(
    error: DynamicSetsPolicyParametersError,
) -> JSONResponse:
    """Serialize the 422 refusing a dynamic that sets a policy's parameters."""
    refusal = V2PolicyParametersErrorResponse(
        message=str(error), policy_parameters=list(error.parameter_names)
    )
    return JSONResponse(status_code=422, content=refusal.model_dump(mode="json"))


def _dynamic_operation(
    operation: Callable[[], OperationT],
) -> OperationT | JSONResponse:
    def refused() -> OperationT | JSONResponse:
        try:
            return operation()
        except DynamicSetsPolicyParametersError as error:
            return _policy_parameters_response(error)

    return run_v2_operation(
        refused,
        DYNAMIC_ERROR_MAPPINGS,
        fallback_message="V2 dynamic operation failed",
    )


def build_v2_dynamic_router(dependencies: NativeRouteDependencies) -> APIRouter:
    """Build native dynamic routes without opening a database connection."""
    router = APIRouter(prefix="/v2", responses=DYNAMIC_ERROR_RESPONSES)
    service_factory = _service_factory(dependencies)

    @router.post(
        "/dynamics",
        response_model=DynamicDetailResponse,
        status_code=201,
        responses={
            200: {
                "model": DynamicDetailResponse,
                "description": "Equivalent immutable content already exists.",
            }
        },
        summary="Create or find an immutable dynamic",
        description=(
            "Binds the model assumptions to the catalog of policyengine_version, "
            "or of the running PolicyEngine.py version when it names none, and "
            "stores them once per content hash, as policies are stored. Every "
            "parameter must be under gov.simulation, or in the US also "
            "simulation; any other answers 422 with code policy_parameters. "
            "Answers 201 when it creates the dynamic and 200 when identical "
            "content is already stored. There is no list route."
        ),
    )
    def create_dynamic(
        body: DynamicCreateRequest,
        query: DynamicCreateQueryDependency,
        _size: Annotated[None, Depends(enforce_dynamic_request_size)],
    ) -> DynamicDetailResponse | JSONResponse:
        if body.country_id != query.country_id:
            return v2_error_response(400, "Body country_id must match query country_id")

        def create() -> DynamicDetailResponse | JSONResponse:
            result = service_factory().create_dynamic(
                NativeDynamicCreationInput(
                    **body.model_dump(),
                    policyengine_version=query.policyengine_version,
                )
            )
            response = DynamicDetailResponse(
                result=DynamicDetailResult(item=DynamicItem.from_read(result.item))
            )
            if result.created:
                return response
            return JSONResponse(
                status_code=200, content=response.model_dump(mode="json")
            )

        return _dynamic_operation(create)

    @router.get(
        "/dynamics/{dynamic_id}",
        response_model=DynamicDetailResponse,
        summary="Read one immutable dynamic",
        description=(
            "Returns the country's dynamic with its values, and the parameters "
            "it sets that the running catalog no longer has. Another country's "
            "dynamic answers 404."
        ),
    )
    def get_dynamic(
        dynamic_id: UUID,
        query: DynamicDetailQueryDependency,
    ) -> DynamicDetailResponse | JSONResponse:
        def read() -> DynamicDetailResponse:
            item = service_factory().get_dynamic(
                country_id=query.country_id, dynamic_id=dynamic_id
            )
            return DynamicDetailResponse(
                result=DynamicDetailResult(item=DynamicItem.from_read(item))
            )

        return _dynamic_operation(read)

    return router
