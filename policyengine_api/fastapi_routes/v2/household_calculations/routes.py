"""Native FastAPI routes submitting stored households for calculation, and polling them.

The calculation itself runs on the simulation service, which stores every
calculation as a simulation run; a calculation not saved to an account has no
report. The routes need no account.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from policyengine_api.data.v2.catalog.catalog_selection import (
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    UnsupportedPreviewCountryError,
)
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import (
    _default_v2_household_calculation_service_factory,
)
from policyengine_api.fastapi_routes.v2.errors import V2ErrorMapping, run_v2_operation
from policyengine_api.fastapi_routes.v2.household_calculations.request_models import (
    HouseholdCalculationRequest,
)
from policyengine_api.fastapi_routes.v2.household_calculations.response_models import (
    HOUSEHOLD_CALCULATION_ERROR_RESPONSES,
    HouseholdCalculationItem,
    HouseholdCalculationResponse,
)
from policyengine_api.services.v2.household_calculations.types import (
    SimulationServiceInvalidRequestError,
    SimulationServiceRefusedError,
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.household_calculations.validators import (
    HouseholdCalculationCountryError,
    HouseholdCalculationNotFoundError,
    HouseholdCalculationYearError,
)
from policyengine_api.services.v2.households.validators import HouseholdNotFoundError
from policyengine_api.services.v2.policies.validators import PolicyNotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
        V2HouseholdCalculationResourceService,
    )

OperationT = TypeVar("OperationT")

HOUSEHOLD_CALCULATION_ERROR_MAPPINGS = (
    V2ErrorMapping(
        (
            HouseholdCalculationCountryError,
            HouseholdCalculationYearError,
            SimulationServiceInvalidRequestError,
        ),
        422,
    ),
    V2ErrorMapping(
        (
            HouseholdNotFoundError,
            PolicyNotFoundError,
            HouseholdCalculationNotFoundError,
        ),
        404,
    ),
    V2ErrorMapping(
        (SimulationServiceUnavailableError, SimulationServiceRefusedError), 503
    ),
    V2ErrorMapping(
        (
            MetadataCatalogUnavailableError,
            MetadataCatalogVersionNotFoundError,
            UnsupportedPreviewCountryError,
        ),
        503,
        "The country's catalog version is unavailable",
    ),
    V2ErrorMapping(
        (V2ConfigurationError, SQLAlchemyError),
        503,
        "V2 household calculation storage is unavailable",
    ),
)


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2HouseholdCalculationResourceService]:
    if dependencies.v2_household_calculation_service_factory is not None:
        return dependencies.v2_household_calculation_service_factory
    return _default_v2_household_calculation_service_factory


def _calculation_operation(
    operation: Callable[[], OperationT],
) -> OperationT | JSONResponse:
    return run_v2_operation(
        operation,
        HOUSEHOLD_CALCULATION_ERROR_MAPPINGS,
        fallback_message="V2 household calculation failed",
    )


def build_v2_household_calculation_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the household calculation routes without opening any connection."""
    router = APIRouter(prefix="/v2", responses=HOUSEHOLD_CALCULATION_ERROR_RESPONSES)
    service_factory = _service_factory(dependencies)

    @router.post(
        "/household-calculations",
        response_model=HouseholdCalculationResponse,
        status_code=202,
        summary="Calculate a stored household under a stored policy",
    )
    def submit_household_calculation(
        body: HouseholdCalculationRequest,
    ) -> HouseholdCalculationResponse | JSONResponse:
        def submit() -> HouseholdCalculationResponse:
            calculation = service_factory().submit_calculation(body.to_service_input())
            return HouseholdCalculationResponse(
                result=HouseholdCalculationItem.from_read(calculation)
            )

        return _calculation_operation(submit)

    @router.get(
        "/household-calculations/{calculation_id}",
        response_model=HouseholdCalculationResponse,
        summary="Read a household calculation and its result",
    )
    def get_household_calculation(
        calculation_id: UUID,
    ) -> HouseholdCalculationResponse | JSONResponse:
        def read() -> HouseholdCalculationResponse:
            calculation = service_factory().get_calculation(calculation_id)
            return HouseholdCalculationResponse(
                result=HouseholdCalculationItem.from_read(calculation)
            )

        return _calculation_operation(read)

    return router
