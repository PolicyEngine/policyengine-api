"""Native FastAPI routes for v2 simulations.

The routes need no user credential: a user keeps a simulation through
``/v2/user-simulations``. Simulations and their runs are read from the
detailed-save tables the simulation service writes; reading never calls it.
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
from policyengine_api.fastapi_routes.v2.errors_support import V2ErrorMapping
from policyengine_api.fastapi_routes.v2.simulation_resources_support import (
    simulation_resource_operation,
)
from policyengine_api.fastapi_routes.v2.simulations.response_models import (
    READ_RESPONSES,
    SIMULATION_ERROR_RESPONSES,
    SimulationDetailResponse,
    SimulationDetailResult,
    SimulationItem,
)
from policyengine_api.query_parameters import SimulationDetailQuery
from policyengine_api.services.v2.stored_simulations.validators import (
    SimulationStorageError,
    StoredSimulationNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
        V2StoredSimulationResourceService,
    )

SimulationDetailQueryDependency = Annotated[
    SimulationDetailQuery, Depends(query_dependency(SimulationDetailQuery))
]

# Refusals a caller can act on carry their own message and are not logged.
SIMULATION_REFUSALS: tuple[type[Exception], ...] = (StoredSimulationNotFoundError,)
SIMULATION_ERROR_MAPPINGS = (
    V2ErrorMapping((StoredSimulationNotFoundError,), 404),
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
