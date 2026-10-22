"""Native health and simulation gateway health routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies


class HealthResponse(BaseModel):
    """Health-check result showing that the API has warmed up and can serve requests."""

    status: Literal["healthy"]


class HealthNotReadyResponse(BaseModel):
    """Health-check result while warmup runs or the configuration is invalid."""

    status: Literal["not_ready"]


class SimulationGatewayHealthResponse(BaseModel):
    """Health-check result showing that the API and its simulation gateway are up."""

    status: Literal["healthy"]
    simulation_gateway: Literal["healthy"]


def build_core_health_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the health and simulation gateway health routes.

    ``/health`` answers 503 until the readiness probe passes: the startup
    warmup has finished and the runtime configuration is valid. The Cloud Run
    startup probe and the deployment health checks poll it, so a revision
    receives no traffic, and is not promoted, before it can serve.
    """
    router = APIRouter()

    @router.get(
        "/health",
        response_model=HealthResponse,
        responses={
            503: {
                "model": HealthNotReadyResponse,
                "description": (
                    "Startup warmup has not finished, or the runtime "
                    "configuration is invalid."
                ),
            }
        },
    )
    def health() -> HealthResponse | JSONResponse:
        if not dependencies.readiness_probe():
            return JSONResponse(
                status_code=503,
                content=HealthNotReadyResponse(status="not_ready").model_dump(),
            )
        return HealthResponse(status="healthy")

    @router.get(
        "/simulation-gateway-check",
        response_model=SimulationGatewayHealthResponse,
        include_in_schema=False,
    )
    def simulation_gateway_health() -> SimulationGatewayHealthResponse:
        try:
            gateway_healthy = dependencies.gateway_client_factory().health_check()
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail="Simulation gateway client initialization failed",
            ) from error

        if not gateway_healthy:
            raise HTTPException(
                status_code=503,
                detail="Simulation gateway health check failed",
            )

        return SimulationGatewayHealthResponse(
            status="healthy",
            simulation_gateway="healthy",
        )

    return router
