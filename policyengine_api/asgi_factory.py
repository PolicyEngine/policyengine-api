"""FastAPI shell for serving the existing Flask API through ASGI."""

from __future__ import annotations

import time

from a2wsgi import WSGIMiddleware
from fastapi import FastAPI
from fastapi.routing import APIRoute
from policyengine_api.constants import VERSION
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.fastapi_routes.health import build_core_health_router
from policyengine_api.fastapi_routes.health import build_readiness_router
from policyengine_api.fastapi_routes.metadata import build_metadata_router
from policyengine_api.fastapi_routes.specification import (
    build_specification_router,
)
from policyengine_api.migration_flags import (
    BACKEND_RESPONSE_HEADER,
    RouteImplementation,
    RouteImplementationSettings,
    get_api_host_backend,
)
from policyengine_api.migration_logging import log_migration_request
from policyengine_api.request_context import (
    REQUEST_ID_HEADER,
    _asgi_request_id,
    generate_request_id,
)
from starlette.datastructures import MutableHeaders
from starlette.middleware.gzip import GZipMiddleware


def _add_vary_origin(response) -> None:
    vary = response.headers.get("Vary")
    if vary is None:
        response.headers["Vary"] = "Origin"
        return
    if "origin" not in {value.strip().lower() for value in vary.split(",")}:
        response.headers["Vary"] = f"{vary}, Origin"


def create_asgi_app(
    wsgi_app,
    *,
    route_settings: RouteImplementationSettings | None = None,
    dependencies: NativeRouteDependencies | None = None,
) -> FastAPI:
    """Create the Stage 2 FastAPI shell around the existing Flask app."""

    if route_settings is None:
        route_settings = RouteImplementationSettings.from_environment()
    if dependencies is None:
        dependencies = NativeRouteDependencies.defaults()

    app = FastAPI(
        title="PolicyEngine API",
        version=VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    # compresslevel 4 instead of starlette's default 9: /us/metadata is ~70MB
    # raw, and level-9 compression inside the request costs seconds of CPU on
    # Cloud Run (where no nginx sidecar handles gzip, unlike App Engine flex).
    # Measured on the real payload: level 9 = 5.5s -> 9.0MB, level 4 = 0.7s ->
    # 9.9MB — 7.5x faster for ~10% larger output.
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=4)

    @app.middleware("http")
    async def add_cors_for_native_routes(request, call_next):
        started_at = time.time()
        request_id = request.headers.get(REQUEST_ID_HEADER) or generate_request_id()
        MutableHeaders(scope=request.scope)[REQUEST_ID_HEADER] = request_id
        context_token = _asgi_request_id.set(request_id)

        def log_native_route(status_code: int) -> None:
            if not isinstance(request.scope.get("route"), APIRoute):
                return
            try:
                log_migration_request(
                    request_id=request_id,
                    method=request.method,
                    path=request.url.path,
                    status_code=status_code,
                    started_at=started_at,
                    country_id=request.path_params.get("country_id"),
                    route_impl=RouteImplementation.FASTAPI_NATIVE,
                )
            except Exception:
                pass

        try:
            try:
                response = await call_next(request)
            except Exception:
                log_native_route(500)
                raise
            response.headers[REQUEST_ID_HEADER] = request_id
            if BACKEND_RESPONSE_HEADER not in response.headers:
                response.headers[BACKEND_RESPONSE_HEADER] = get_api_host_backend()
            origin = request.headers.get("origin")
            if origin and "access-control-allow-origin" not in response.headers:
                response.headers["Access-Control-Allow-Origin"] = origin
                _add_vary_origin(response)
            log_native_route(response.status_code)
            return response
        finally:
            _asgi_request_id.reset(context_token)

    app.include_router(build_core_health_router(dependencies))
    if route_settings.health is RouteImplementation.FASTAPI_NATIVE:
        app.include_router(build_readiness_router(dependencies))
    if route_settings.specification is RouteImplementation.FASTAPI_NATIVE:
        app.include_router(build_specification_router(dependencies))
    if route_settings.metadata is RouteImplementation.FASTAPI_NATIVE:
        app.include_router(build_metadata_router(dependencies))

    app.mount("/", WSGIMiddleware(wsgi_app))
    return app
