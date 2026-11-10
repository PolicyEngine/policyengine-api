"""Native FastAPI routes calculating stored households, and reading the results.

The calculation runs on the simulation service, which records it as a job in
``household_jobs``; the routes need no account. Submitting sends the
simulation service the stored household's and policy's IDs once the Public
API's own checks pass; reading reads the job from the database and never
calls the simulation service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar
from uuid import UUID

from fastapi import APIRouter
from starlette.responses import JSONResponse

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import (
    _default_v2_household_calculation_service_factory,
)
from policyengine_api.fastapi_routes.v2.errors_support import (
    V2ErrorMapping,
    run_v2_operation,
    v2_missing_parameters_response,
)
from policyengine_api.fastapi_routes.v2.household_calculations.request_models import (
    HouseholdCalculationRequest,
)
from policyengine_api.fastapi_routes.v2.household_calculations.response_models import (
    HOUSEHOLD_CALCULATION_ERROR_RESPONSES,
    SUBMISSION_REFUSAL_RESPONSES,
    HouseholdCalculationItem,
    HouseholdCalculationResponse,
    HouseholdCalculationResult,
    HouseholdCalculationSubmittedItem,
    HouseholdCalculationSubmittedResponse,
    HouseholdCalculationSubmittedResult,
)
from policyengine_api.services.v2.household_calculations.types import (
    SimulationServiceAnswerUnreadableError,
    SimulationServiceInvalidRequestError,
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.household_calculations.validators import (
    HouseholdCalculationCountryError,
    HouseholdCalculationNotFoundError,
    HouseholdCalculationResultUnreadableError,
    HouseholdCalculationStorageError,
    HouseholdCalculationYearError,
)
from policyengine_api.services.v2.households.validators import HouseholdNotFoundError
from policyengine_api.services.v2.policies.validators import (
    PolicyNotFoundError,
    PolicyParametersMissingError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
        V2HouseholdCalculationResourceService,
    )

OperationT = TypeVar("OperationT")

STORAGE_UNAVAILABLE = "V2 household calculation storage is unavailable"
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
    V2ErrorMapping((SimulationServiceUnavailableError,), 503),
    # The simulation service created the job, so this is not a 503, which
    # invites the caller to submit again.
    V2ErrorMapping((SimulationServiceAnswerUnreadableError,), 502),
    V2ErrorMapping(
        (HouseholdCalculationResultUnreadableError,),
        500,
        "Stored household calculation result is unreadable",
    ),
    V2ErrorMapping(
        (HouseholdCalculationStorageError, V2ConfigurationError),
        503,
        STORAGE_UNAVAILABLE,
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
        response_model=HouseholdCalculationSubmittedResponse,
        status_code=202,
        responses=SUBMISSION_REFUSAL_RESPONSES,
        summary="Calculate a stored household under a stored policy",
    )
    def submit_household_calculation(
        body: HouseholdCalculationRequest,
    ) -> HouseholdCalculationSubmittedResponse | JSONResponse:
        def submit() -> HouseholdCalculationSubmittedResponse | JSONResponse:
            try:
                calculation = service_factory().submit_calculation(
                    body.to_service_input()
                )
            except PolicyParametersMissingError as error:
                return v2_missing_parameters_response(
                    str(error), error.missing_parameters
                )
            return HouseholdCalculationSubmittedResponse(
                result=HouseholdCalculationSubmittedResult(
                    item=HouseholdCalculationSubmittedItem.from_submitted(calculation)
                )
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
                result=HouseholdCalculationResult(
                    item=HouseholdCalculationItem.from_read(calculation)
                )
            )

        return _calculation_operation(read)

    return router
