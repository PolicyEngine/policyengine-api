"""Native FastAPI routes for v2 simulations.

The routes need no user credential: a user keeps a simulation through
``/v2/user-simulations``. Simulations and their runs are read from the
detailed-save tables the simulation service writes; reading never calls it.
Creating a simulation checks it, has the simulation service create and start
it, and reads it back.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import (
    _default_v2_stored_simulation_service_factory,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.errors_support import (
    V2ErrorMapping,
    v2_error_response,
)
from policyengine_api.fastapi_routes.v2.simulation_resources_support import (
    SUBMISSION_ERROR_MAPPINGS,
    SUBMISSION_REFUSALS,
    created_record_unreadable_answer,
    simulation_resource_operation,
)
from policyengine_api.fastapi_routes.v2.simulations.request_models import (
    SimulationCreateRequest,
)
from policyengine_api.fastapi_routes.v2.simulations.response_models import (
    CREATE_RESPONSES,
    READ_RESPONSES,
    SIMULATION_ERROR_RESPONSES,
    CreatedSimulationUnreadableResponse,
    SimulationDetailResponse,
    SimulationDetailResult,
    SimulationItem,
)
from policyengine_api.fastapi_routes.v2.user_resources_support import (
    request_size_limit,
)
from policyengine_api.query_parameters import (
    SimulationCreateQuery,
    SimulationDetailQuery,
)
from policyengine_api.services.v2.stored_simulations.validators import (
    CreatedSimulationUnreadableError,
    SimulationStorageError,
    StoredSimulationNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
        V2StoredSimulationResourceService,
    )

MAXIMUM_SIMULATION_REQUEST_BYTES = 16 * 1024
enforce_simulation_request_size = request_size_limit(
    MAXIMUM_SIMULATION_REQUEST_BYTES, label="16 KiB"
)
SimulationCreateQueryDependency = Annotated[
    SimulationCreateQuery, Depends(query_dependency(SimulationCreateQuery))
]
SimulationDetailQueryDependency = Annotated[
    SimulationDetailQuery, Depends(query_dependency(SimulationDetailQuery))
]

# Refusals a caller can act on carry their own message and are not logged.
SIMULATION_REFUSALS: tuple[type[Exception], ...] = (
    StoredSimulationNotFoundError,
    *SUBMISSION_REFUSALS,
)
SIMULATION_ERROR_MAPPINGS = (
    V2ErrorMapping((StoredSimulationNotFoundError,), 404),
    *SUBMISSION_ERROR_MAPPINGS,
    V2ErrorMapping(
        (V2ConfigurationError, SimulationStorageError),
        503,
        "V2 simulation storage is unavailable",
    ),
)

OperationT = TypeVar("OperationT")


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2StoredSimulationResourceService]:
    if dependencies.v2_stored_simulation_service_factory is not None:
        return dependencies.v2_stored_simulation_service_factory
    return _default_v2_stored_simulation_service_factory


def _simulation_operation(
    operation: Callable[[], OperationT],
) -> OperationT | JSONResponse:
    return simulation_resource_operation(
        operation,
        SIMULATION_ERROR_MAPPINGS,
        refusals=SIMULATION_REFUSALS,
        event="v2_simulation_operation_failed",
        fallback_message="V2 simulation operation failed",
    )


def build_v2_simulation_router(dependencies: NativeRouteDependencies) -> APIRouter:
    """Build the simulation routes without opening a connection."""
    router = APIRouter(prefix="/v2", responses=SIMULATION_ERROR_RESPONSES)
    service_factory = _service_factory(dependencies)

    @router.post(
        "/simulations",
        response_model=SimulationDetailResponse,
        status_code=201,
        responses=CREATE_RESPONSES,
        summary="Create an economy simulation",
        description=(
            "Checks that the country has economy calculations and stores the "
            "named policy, then has the simulation service create the "
            "simulation and its first run on its default worker's "
            "PolicyEngine.py version, and start the run. Answers the simulation "
            "as stored, with its pending run. A created simulation that cannot "
            "be read back answers 502 with its simulation_id."
        ),
    )
    def create_simulation(
        body: SimulationCreateRequest,
        query: SimulationCreateQueryDependency,
        _size: Annotated[None, Depends(enforce_simulation_request_size)],
    ) -> SimulationDetailResponse | JSONResponse:
        if body.country_id != query.country_id:
            return v2_error_response(400, "Body country_id must match query country_id")

        def create() -> SimulationDetailResponse | JSONResponse:
            try:
                simulation = service_factory().create_simulation(body)
            except CreatedSimulationUnreadableError as error:
                return created_record_unreadable_answer(
                    "v2_created_simulation_unreadable",
                    error,
                    CreatedSimulationUnreadableResponse(
                        message=(
                            f"The simulation service created simulation "
                            f"{error.simulation_id}, but it could not be read "
                            f"back. Read it with GET /v2/simulations/"
                            f"{error.simulation_id}?country_id={error.country_id} "
                            "rather than submitting it again."
                        ),
                        simulation_id=error.simulation_id,
                    ),
                )
            return SimulationDetailResponse(
                result=SimulationDetailResult(item=SimulationItem.from_read(simulation))
            )

        return _simulation_operation(create)

    @router.get(
        "/simulations/{simulation_id}",
        response_model=SimulationDetailResponse,
        responses=READ_RESPONSES,
        summary="Read a simulation",
        description=(
            "Returns the simulation, its newest run whatever its year, status "
            "and versions, and the versions the Public API runs now. A "
            "simulation belongs to the country whose model its catalog version "
            "is of; reading starts no run."
        ),
    )
    def get_simulation(
        simulation_id: UUID,
        query: SimulationDetailQueryDependency,
    ) -> SimulationDetailResponse | JSONResponse:
        def read() -> SimulationDetailResponse:
            simulation = service_factory().get_simulation(
                country_id=query.country_id, simulation_id=simulation_id
            )
            return SimulationDetailResponse(
                result=SimulationDetailResult(item=SimulationItem.from_read(simulation))
            )

        return _simulation_operation(read)

    return router
