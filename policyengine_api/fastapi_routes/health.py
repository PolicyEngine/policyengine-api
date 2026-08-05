"""Native health, liveness, and readiness routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from pydantic import BaseModel
from starlette.responses import PlainTextResponse


class HealthResponse(BaseModel):
    status: Literal["healthy"]


class SimulationGatewayHealthResponse(BaseModel):
    status: Literal["healthy"]
    simulation_gateway: Literal["healthy"]


def build_core_health_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build health routes that were native before Stage 6."""
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
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


def build_readiness_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build selectable native liveness and readiness routes."""
    router = APIRouter()

    @router.get(
        "/liveness-check",
        response_class=PlainTextResponse,
        include_in_schema=False,
    )
    def liveness_check() -> PlainTextResponse:
        return PlainTextResponse("OK", status_code=200)

    @router.get(
        "/readiness-check",
        response_class=PlainTextResponse,
        include_in_schema=False,
    )
    def readiness_check() -> PlainTextResponse:
        if not dependencies.readiness_probe():
            return PlainTextResponse("NOT READY", status_code=503)
        return PlainTextResponse("OK", status_code=200)

    return router
