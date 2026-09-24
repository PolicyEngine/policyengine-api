"""FastAPI shell for serving the existing Flask API through ASGI."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
import time

from a2wsgi import WSGIMiddleware
from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from policyengine_api.constants import VERSION
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.fastapi_routes.health import build_core_health_router
from policyengine_api.fastapi_routes.health import build_readiness_router
from policyengine_api.fastapi_routes.metadata import build_metadata_router
from policyengine_api.fastapi_routes.specification import (
    build_specification_router,
)
from policyengine_api.fastapi_routes.v2.errors import (
    V2RequestTooLargeError,
    v2_error_response,
)
from policyengine_api.fastapi_routes.v2.routes import build_v2_router
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.migration_logging import log_migration_request
from policyengine_api.observability import get_runtime
from policyengine_api.request_context import (
    REQUEST_ID_HEADER,
    _asgi_observability_id,
    _asgi_request_id,
    generate_request_id,
    resolve_observability_id,
)
from policyengine_observability import ObservabilityRuntime
from policyengine_api.observability.identifiers import OBSERVABILITY_ID_HEADER
from policyengine_api.request_context import current_observability_id
from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Match, Mount
from starlette.types import ASGIApp


def _apply_request_id_header(
    response: Response,
    request_id: str,
) -> None:
    response.headers[REQUEST_ID_HEADER] = request_id


def _apply_observability_id_header(
    response: Response,
    observability_id: str,
) -> None:
    response.headers[OBSERVABILITY_ID_HEADER] = observability_id


def _is_native_request(app: FastAPI, scope: dict) -> bool:
    """Return whether FastAPI, rather than the mounted Flask app, handles it."""

    for route in app.router.routes:
        match, _ = route.matches(scope)
        if match is Match.FULL:
            return not isinstance(route, Mount)
    return False


def create_asgi_app(
    wsgi_app,
    *,
    route_settings: RouteImplementationSettings | None = None,
    dependencies: NativeRouteDependencies | None = None,
    shutdown_callback: Callable[[], None] | None = None,
    observability_runtime: ObservabilityRuntime | None = None,
) -> ASGIApp:
    """Create the Stage 2 FastAPI shell around the existing Flask app."""

    if route_settings is None:
        route_settings = RouteImplementationSettings.from_environment()
    if dependencies is None:
        dependencies = NativeRouteDependencies.defaults()
    request_runtime = observability_runtime or get_runtime()

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
        _apply_request_id_header(response, request_id)
        observability_id = getattr(
            request.state,
            "policyengine_observability_id",
            None,
        ) or resolve_observability_id(request.headers.get(OBSERVABILITY_ID_HEADER))
        _apply_observability_id_header(response, observability_id)
        return response

    @app.exception_handler(RequestValidationError)
    async def typed_v2_request_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> Response:
        if request.url.path.startswith("/v2/"):
            return v2_error_response(422, "Invalid API v2 request")
        return await request_validation_exception_handler(request, error)

    @app.exception_handler(V2RequestTooLargeError)
    async def oversized_v2_request(
        _request: Request,
        error: V2RequestTooLargeError,
    ) -> Response:
        return v2_error_response(413, str(error))

    @app.middleware("http")
    async def add_request_context_and_migration_logging(request, call_next):
        started_at = time.time()
        request_id = request.headers.get(REQUEST_ID_HEADER) or generate_request_id()
        observability_id = resolve_observability_id(
            request.headers.get(OBSERVABILITY_ID_HEADER)
        )
        MutableHeaders(scope=request.scope)[REQUEST_ID_HEADER] = request_id
        MutableHeaders(scope=request.scope)[OBSERVABILITY_ID_HEADER] = observability_id
        request.state.policyengine_request_id = request_id
        request.state.policyengine_observability_id = observability_id
        context_token = _asgi_request_id.set(request_id)
        observability_context_token = _asgi_observability_id.set(observability_id)
        native_request = _is_native_request(app, request.scope)
        initial_route = request.url.path

        if native_request:
            try:
                runtime_request_id = request_runtime.begin_request(
                    headers={
                        **dict(request.headers),
                        REQUEST_ID_HEADER: request_id,
                        OBSERVABILITY_ID_HEADER: observability_id,
                    },
                    method=request.method,
                    route=initial_route,
                )
                if isinstance(runtime_request_id, str) and runtime_request_id:
                    request_id = runtime_request_id
                    MutableHeaders(scope=request.scope)[REQUEST_ID_HEADER] = request_id
                    request.state.policyengine_request_id = request_id
                    _asgi_request_id.reset(context_token)
                    context_token = _asgi_request_id.set(request_id)
            except Exception:
                pass
            try:
                request_runtime.set_context(
                    request_id=request_id,
                    observability_id=observability_id,
                )
            except Exception:
                pass

        def log_native_route(status_code: int) -> None:
            if not native_request:
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

        def finish_native_route(
            status_code: int,
            error: BaseException | None = None,
        ) -> None:
            if not native_request:
                return
            resolved_route = getattr(request.scope.get("route"), "path", initial_route)
            try:
                request_runtime.update_request_route(resolved_route)
            except Exception:
                pass
            try:
                request_runtime.update_request_status(status_code)
            except Exception:
                pass
            try:
                request_runtime.end_request(
                    status_code=status_code,
                    error=error,
                )
            except Exception:
                pass

        try:
            try:
                response = await call_next(request)
            except Exception as error:
                log_native_route(500)
                finish_native_route(500, error)
                raise
            if native_request:
                try:
                    for name, value in request_runtime.response_headers().items():
                        response.headers[name] = value
                except Exception:
                    pass
            _apply_request_id_header(response, request_id)
            response_observability_id = (
                response.headers.get(OBSERVABILITY_ID_HEADER)
                or current_observability_id()
                or observability_id
            )
            _apply_observability_id_header(response, response_observability_id)
            log_native_route(response.status_code)
            finish_native_route(response.status_code)
            return response
        finally:
            _asgi_request_id.reset(context_token)
            _asgi_observability_id.reset(observability_context_token)

    app.include_router(build_core_health_router(dependencies))
    app.include_router(build_v2_router(dependencies))
    if route_settings.health is RouteImplementation.FASTAPI_NATIVE:
        app.include_router(build_readiness_router(dependencies))
    if route_settings.specification is RouteImplementation.FASTAPI_NATIVE:
        app.include_router(build_specification_router(dependencies))
    if route_settings.metadata is RouteImplementation.FASTAPI_NATIVE:
        app.include_router(build_metadata_router(dependencies))

    app.mount("/", WSGIMiddleware(wsgi_app))
    # The public API already permits every web origin. Use the standard ASGI
    # implementation while preserving the existing reflected-origin response.
    return CORSMiddleware(
        app=app,
        allow_origin_regex=".*",
        allow_methods=["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER, OBSERVABILITY_ID_HEADER],
        allow_credentials=False,
        max_age=600,
    )
