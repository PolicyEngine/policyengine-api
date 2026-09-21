"""Authenticated internal routes backed by canonical comparison-run services."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2ComparisonRunResourceService,
)
from policyengine_api.fastapi_routes.v2.comparison_runs.auth import (
    Stage12PersistenceAuthenticator,
)
from policyengine_api.fastapi_routes.v2.comparison_runs.request_models import (
    SimulationInvocationRequest,
)
from policyengine_api.fastapi_routes.v2.comparison_runs.response_models import (
    ComparisonReportPersistenceResponse,
    ComparisonReportResponse,
    ComparisonSimulationListResponse,
    ComparisonSimulationPersistenceResponse,
    ComparisonSimulationResponse,
)
from policyengine_api.services.v2.comparison_runs.types import (
    ComparisonReportRecord,
    ComparisonSimulationRecord,
)
from policyengine_api.services.v2.comparison_runs.validators import (
    ComparisonRunIdentityError,
    ComparisonRunNotFoundError,
    ComparisonRunStateTransitionError,
)


OperationT = TypeVar("OperationT")


def _operation(operation: Callable[[], OperationT]) -> OperationT | JSONResponse:
    try:
        return operation()
    except ComparisonRunNotFoundError:
        return JSONResponse(
            status_code=404,
            content={"detail": "comparison record was not found"},
        )
    except (ComparisonRunIdentityError, ComparisonRunStateTransitionError):
        return JSONResponse(
            status_code=409,
            content={"detail": "comparison record conflicts with stored state"},
        )
    except (V2ConfigurationError, SQLAlchemyError):
        return JSONResponse(
            status_code=503,
            content={"detail": "comparison persistence is unavailable"},
        )
    except Exception:  # noqa: BLE001 - never expose persistence internals
        return JSONResponse(
            status_code=500,
            content={"detail": "comparison persistence operation failed"},
        )


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2ComparisonRunResourceService]:
    if dependencies.v2_comparison_run_service_factory is not None:
        return dependencies.v2_comparison_run_service_factory
    from policyengine_api.fastapi_routes.dependencies import (
        _default_v2_comparison_run_service_factory,
    )

    return _default_v2_comparison_run_service_factory


def build_stage12_comparison_run_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the temporary private persistence API used only through Stage 12."""

    # TEMPORARY(Stage 12): Remove these routes with the comparison tables when
    # Stage 14 makes canonical simulations, reports, and report runs authoritative.
    authenticator = (
        dependencies.stage12_persistence_authenticator
        or Stage12PersistenceAuthenticator()
    )
    router = APIRouter(
        prefix="/internal/stage12/comparison-runs",
        include_in_schema=False,
        dependencies=[Depends(authenticator)],
    )
    service_factory = _service_factory(dependencies)

    @router.post("/reports/resolve", response_model=ComparisonReportPersistenceResponse)
    def resolve_report(
        body: ComparisonReportRecord,
    ) -> ComparisonReportPersistenceResponse | JSONResponse:
        def persist() -> ComparisonReportPersistenceResponse:
            result = service_factory().create_or_resolve_report(body)
            return ComparisonReportPersistenceResponse(
                record=result.record,
                created=result.created,
            )

        return _operation(persist)

    @router.get("/reports/{evaluation_id}", response_model=ComparisonReportResponse)
    def get_report(evaluation_id: UUID) -> ComparisonReportResponse | JSONResponse:
        return _operation(
            lambda: ComparisonReportResponse(
                record=service_factory().get_report(evaluation_id)
            )
        )

    @router.get(
        "/reports/{evaluation_id}/simulations",
        response_model=ComparisonSimulationListResponse,
    )
    def list_simulations(
        evaluation_id: UUID,
    ) -> ComparisonSimulationListResponse | JSONResponse:
        return _operation(
            lambda: ComparisonSimulationListResponse(
                items=service_factory().list_simulations(evaluation_id)
            )
        )

    @router.put(
        "/reports/{evaluation_id}/lifecycle",
        response_model=ComparisonReportResponse,
    )
    def replace_report_lifecycle(
        evaluation_id: UUID,
        body: ComparisonReportRecord,
    ) -> ComparisonReportResponse | JSONResponse:
        if body.evaluation_id != evaluation_id:
            return JSONResponse(
                status_code=400,
                content={"detail": "path and body report identifiers differ"},
            )
        return _operation(
            lambda: ComparisonReportResponse(
                record=service_factory().replace_report_lifecycle(body)
            )
        )

    @router.put(
        "/reports/{evaluation_id}/comparison",
        response_model=ComparisonReportResponse,
    )
    def replace_report_comparison(
        evaluation_id: UUID,
        body: ComparisonReportRecord,
    ) -> ComparisonReportResponse | JSONResponse:
        if body.evaluation_id != evaluation_id:
            return JSONResponse(
                status_code=400,
                content={"detail": "path and body report identifiers differ"},
            )
        return _operation(
            lambda: ComparisonReportResponse(
                record=service_factory().replace_report_result_comparison(body)
            )
        )

    @router.post(
        "/simulations/resolve",
        response_model=ComparisonSimulationPersistenceResponse,
    )
    def resolve_simulation(
        body: ComparisonSimulationRecord,
    ) -> ComparisonSimulationPersistenceResponse | JSONResponse:
        def persist() -> ComparisonSimulationPersistenceResponse:
            result = service_factory().create_or_resolve_simulation(body)
            return ComparisonSimulationPersistenceResponse(
                record=result.record,
                created=result.created,
            )

        return _operation(persist)

    @router.get(
        "/simulations/{simulation_execution_id}",
        response_model=ComparisonSimulationResponse,
    )
    def get_simulation(
        simulation_execution_id: UUID,
    ) -> ComparisonSimulationResponse | JSONResponse:
        return _operation(
            lambda: ComparisonSimulationResponse(
                record=service_factory().get_simulation(simulation_execution_id)
            )
        )

    @router.put(
        "/simulations/{simulation_execution_id}/lifecycle",
        response_model=ComparisonSimulationResponse,
    )
    def replace_simulation_lifecycle(
        simulation_execution_id: UUID,
        body: ComparisonSimulationRecord,
    ) -> ComparisonSimulationResponse | JSONResponse:
        if body.simulation_execution_id != simulation_execution_id:
            return JSONResponse(
                status_code=400,
                content={"detail": "path and body simulation identifiers differ"},
            )
        return _operation(
            lambda: ComparisonSimulationResponse(
                record=service_factory().replace_simulation_lifecycle(body)
            )
        )

    @router.post(
        "/simulations/{simulation_execution_id}/invocation",
        response_model=ComparisonSimulationResponse,
    )
    def attach_simulation_invocation_route(
        simulation_execution_id: UUID,
        body: SimulationInvocationRequest,
    ) -> ComparisonSimulationResponse | JSONResponse:
        return _operation(
            lambda: ComparisonSimulationResponse(
                record=service_factory().attach_simulation_invocation(
                    simulation_execution_id=simulation_execution_id,
                    expected_placeholder=body.expected_placeholder,
                    modal_invocation_id=body.modal_invocation_id,
                    updated_at=body.updated_at,
                )
            )
        )

    return router
