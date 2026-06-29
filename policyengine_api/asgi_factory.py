"""FastAPI shell for serving the existing Flask API through ASGI."""

from __future__ import annotations

import time
import uuid
from typing import Literal

from a2wsgi import WSGIMiddleware
from fastapi import FastAPI, HTTPException
from policyengine_api.constants import VERSION
from policyengine_api.migration_logging import log_migration_request
from pydantic import BaseModel
from starlette.middleware.gzip import GZipMiddleware

FASTAPI_NATIVE_LOGGED_PATHS = frozenset(
    {
        "/health",
        "/simulation-gateway-check",
    }
)


class HealthResponse(BaseModel):
    status: Literal["healthy"]


class SimulationGatewayHealthResponse(BaseModel):
    status: Literal["healthy"]
    simulation_gateway: Literal["healthy"]


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
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.middleware("http")
    async def add_cors_for_native_routes(request, call_next):
        started_at = time.time()
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        response = await call_next(request)
        origin = request.headers.get("origin")
        if origin and "access-control-allow-origin" not in response.headers:
            response.headers["Access-Control-Allow-Origin"] = origin
            _add_vary_origin(response)
        if request.url.path in FASTAPI_NATIVE_LOGGED_PATHS:
            try:
                log_migration_request(
                    request_id=request_id,
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    started_at=started_at,
                )
            except Exception:
                pass
        return response

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="healthy")

    @app.get(
        "/simulation-gateway-check",
        response_model=SimulationGatewayHealthResponse,
        include_in_schema=False,
    )
    def simulation_gateway_health() -> SimulationGatewayHealthResponse:
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
