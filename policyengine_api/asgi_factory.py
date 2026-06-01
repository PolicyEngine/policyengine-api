"""FastAPI shell for serving the existing Flask API through ASGI."""

from __future__ import annotations

import os
from typing import Literal

from a2wsgi import WSGIMiddleware
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from policyengine_api.constants import VERSION


class HealthResponse(BaseModel):
    status: Literal["healthy"]


class SimulationGatewayHealthResponse(BaseModel):
    status: Literal["healthy"]
    simulation_gateway: Literal["healthy"]


def _internal_probes_enabled() -> bool:
    return os.environ.get("CLOUD_RUN_INTERNAL_PROBES", "").lower() in {
        "1",
        "true",
        "yes",
    }


def _add_vary_origin(response) -> None:
    vary = response.headers.get("Vary")
    if vary is None:
        response.headers["Vary"] = "Origin"
        return
    if "origin" not in {value.strip().lower() for value in vary.split(",")}:
        response.headers["Vary"] = f"{vary}, Origin"


def create_asgi_app(wsgi_app) -> FastAPI:
    """Create the Stage 2 FastAPI shell around the existing Flask app."""

    app = FastAPI(
        title="PolicyEngine API",
        version=VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def add_cors_for_native_routes(request, call_next):
        response = await call_next(request)
        origin = request.headers.get("origin")
        if origin and "access-control-allow-origin" not in response.headers:
            response.headers["Access-Control-Allow-Origin"] = origin
            _add_vary_origin(response)
        return response

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="healthy")

    @app.get(
        "/health/simulation-gateway",
        response_model=SimulationGatewayHealthResponse,
        include_in_schema=False,
    )
    def simulation_gateway_health() -> SimulationGatewayHealthResponse:
        if not _internal_probes_enabled():
            raise HTTPException(status_code=404, detail="Not found")

        from policyengine_api.libs.simulation_api_modal import SimulationAPIModal

        try:
            gateway_healthy = SimulationAPIModal().health_check()
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

    app.mount("/", WSGIMiddleware(wsgi_app))
    return app
