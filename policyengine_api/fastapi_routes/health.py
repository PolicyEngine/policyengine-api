"""Native health, liveness, and readiness routes."""

from __future__ import annotations

import os
from importlib import metadata as importlib_metadata
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.responses import PlainTextResponse

if TYPE_CHECKING:
    from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies


class HealthResponse(BaseModel):
    """Health-check result showing that the API is up and serving requests."""

    status: Literal["healthy"]


class SimulationGatewayHealthResponse(BaseModel):
    """Health-check result showing that the API and its simulation gateway are up."""

    status: Literal["healthy"]
    simulation_gateway: Literal["healthy"]


class DeploymentResponse(BaseModel):
    """The policyengine.py version this revision serves, and since when.

    ``policyengine_version_live_since`` is when this .py version first went
    live: redeploys that keep the version keep the date. It is null on a
    revision deployed before the deploy recorded it, or outside Cloud Run.
    """

    policyengine_version: str
    policyengine_version_live_since: str | None
    revision: str | None


def build_core_health_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build health routes that were native before Stage 6."""
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="healthy")

    @router.get("/deployment", response_model=DeploymentResponse)
    def deployment() -> DeploymentResponse:
        return DeploymentResponse(
            policyengine_version=importlib_metadata.version("policyengine"),
            policyengine_version_live_since=(
                os.environ.get("POLICYENGINE_VERSION_LIVE_SINCE") or None
            ),
            revision=os.environ.get("K_REVISION") or None,
        )

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
