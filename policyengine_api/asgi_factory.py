"""FastAPI shell for serving the existing Flask API through ASGI."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
import time

from a2wsgi import WSGIMiddleware
from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from policyengine_api.constants import VERSION
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.fastapi_routes.health import build_core_health_router
from policyengine_api.fastapi_routes.health import build_readiness_router
from policyengine_api.fastapi_routes.metadata import build_metadata_router
from policyengine_api.fastapi_routes.specification import (
    build_specification_router,
)
from policyengine_api.fastapi_routes.v2_metadata import build_v2_metadata_router
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.migration_logging import log_migration_request
from policyengine_api.request_context import (
    REQUEST_ID_HEADER,
    _asgi_request_id,
    generate_request_id,
)
from starlette.datastructures import MutableHeaders
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import PlainTextResponse, Response


def _add_vary_origin(response) -> None:
    vary = response.headers.get("Vary")
    if vary is None:
        response.headers["Vary"] = "Origin"
        return
    if "origin" not in {value.strip().lower() for value in vary.split(",")}:
        response.headers["Vary"] = f"{vary}, Origin"


def _apply_shared_response_headers(
    request: Request,
    response: Response,
    request_id: str,
) -> None:
    response.headers[REQUEST_ID_HEADER] = request_id
    origin = request.headers.get("origin")
    if origin and "access-control-allow-origin" not in response.headers:
        response.headers["Access-Control-Allow-Origin"] = origin
        _add_vary_origin(response)


def create_asgi_app(
    wsgi_app,
    *,
    route_settings: RouteImplementationSettings | None = None,
    dependencies: NativeRouteDependencies | None = None,
    shutdown_callback: Callable[[], None] | None = None,
) -> FastAPI:
    """Create the Stage 2 FastAPI shell around the existing Flask app."""

    if route_settings is None:
        route_settings = RouteImplementationSettings.from_environment()
    if dependencies is None:
        dependencies = NativeRouteDependencies.defaults()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            if shutdown_callback is not None:
                shutdown_callback()

    app = FastAPI(
        title="PolicyEngine API",
        version=VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    # compresslevel 4 instead of starlette's default 9: /us/metadata is ~70MB
    # raw, and level-9 compression inside the request costs seconds of CPU on
    # Cloud Run because it does not have an nginx sidecar to handle gzip.
    # Measured on the real payload: level 9 = 5.5s -> 9.0MB, level 4 = 0.7s ->
    # 9.9MB — 7.5x faster for ~10% larger output.
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=4)

    @app.exception_handler(Exception)
    async def add_headers_to_unhandled_errors(
        request: Request,
        _error: Exception,
    ) -> Response:
        response = PlainTextResponse("Internal Server Error", status_code=500)
        request_id = getattr(
            request.state,
            "policyengine_request_id",
            request.headers.get(REQUEST_ID_HEADER) or generate_request_id(),
        )
        _apply_shared_response_headers(request, response, request_id)
        return response

    @app.exception_handler(RequestValidationError)
    async def typed_v2_request_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> Response:
        if request.url.path.startswith("/v2/"):
            from policyengine_api.fastapi_routes.v2_metadata_common import (
                error_response,
            )

            return error_response(422, "Invalid v2 metadata request")
        return await request_validation_exception_handler(request, error)

    @app.middleware("http")
    async def add_cors_for_native_routes(request, call_next):
        started_at = time.time()
        request_id = request.headers.get(REQUEST_ID_HEADER) or generate_request_id()
        MutableHeaders(scope=request.scope)[REQUEST_ID_HEADER] = request_id
        request.state.policyengine_request_id = request_id
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
                    country_id=(
                        request.path_params.get("country_id")
                        or request.query_params.get("country_id")
                    ),
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
            _apply_shared_response_headers(request, response, request_id)
            log_native_route(response.status_code)
            return response
        finally:
            _asgi_request_id.reset(context_token)

    app.include_router(build_core_health_router(dependencies))
    app.include_router(build_v2_metadata_router(dependencies))
    if route_settings.health is RouteImplementation.FASTAPI_NATIVE:
        app.include_router(build_readiness_router(dependencies))
    if route_settings.specification is RouteImplementation.FASTAPI_NATIVE:
        app.include_router(build_specification_router(dependencies))
    if route_settings.metadata is RouteImplementation.FASTAPI_NATIVE:
        app.include_router(build_metadata_router(dependencies))

    app.mount("/", WSGIMiddleware(wsgi_app))
    return app
