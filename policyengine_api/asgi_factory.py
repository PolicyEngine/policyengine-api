"""FastAPI shell for serving the existing Flask API through ASGI."""

from __future__ import annotations

from typing import Literal

from a2wsgi import WSGIMiddleware
from fastapi import FastAPI
from pydantic import BaseModel

from policyengine_api.constants import VERSION


class HealthResponse(BaseModel):
    status: Literal["healthy"]


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

    app.mount("/", WSGIMiddleware(wsgi_app))
    return app
