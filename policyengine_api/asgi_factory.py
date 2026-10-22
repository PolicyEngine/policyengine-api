"""FastAPI shell for serving the existing Flask API through ASGI."""

from __future__ import annotations

import contextlib
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from a2wsgi import WSGIMiddleware
from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Match, Mount

from policyengine_api.constants import VERSION
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.fastapi_routes.health import (
    build_core_health_router,
    build_readiness_router,
)
from policyengine_api.fastapi_routes.metadata import build_metadata_router
from policyengine_api.fastapi_routes.v2.errors import (
    V2AuthenticationRequiredError,
    V2AuthenticationUnavailableError,
    V2PermissionDeniedError,
    V2RequestTooLargeError,
    v2_error_response,
)
from policyengine_api.fastapi_routes.v2.routes import build_v2_router
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.migration_logging import ServedRequest, log_migration_request
from policyengine_api.observability import get_runtime
from policyengine_api.observability.identifiers import (
    OBSERVABILITY_ID_HEADER,
    normalize_observability_id,
)
from policyengine_api.request_context import (
    REQUEST_ID_HEADER,
    _asgi_incoming_observability_id,
    _asgi_observability_id,
    _asgi_request_id,
    current_observability_id,
    generate_request_id,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
    from contextlib import AbstractAsyncContextManager

    from policyengine_observability import ObservabilityRuntime
    from starlette.routing import BaseRoute
    from starlette.types import ASGIApp, Scope


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


def _matched_route_template(routes: Iterable[BaseRoute], scope: Scope) -> str | None:
    for route in routes:
        match, _ = route.matches(scope)
        if match is Match.FULL:
            if isinstance(route, Mount):
                return None
            route_template = getattr(route, "path_format", None) or getattr(
                route, "path", None
            )
            if isinstance(route_template, str):
                return route_template
            included_router = getattr(route, "original_router", None)
            if included_router is not None:
                nested_template = _matched_route_template(
                    included_router.routes,
                    scope,
                )
                if nested_template is not None:
                    return nested_template
    return None


def _native_route_template(app: FastAPI, scope: Scope) -> str | None:
    """Return the matched FastAPI route template, excluding the Flask mount."""
    return _matched_route_template(app.router.routes, scope)


def _bind_request_id(request: Request, request_id: str) -> None:
    """Carry ``request_id`` in the request's headers and state."""
    MutableHeaders(scope=request.scope)[REQUEST_ID_HEADER] = request_id
    request.state.policyengine_request_id = request_id


class _RequestContextTokens:
    """Set one ASGI request's context variables, and reset them when it ends."""

    def __init__(self, request_id: str, incoming_observability_id: str | None) -> None:
        """Set the request ID, no observability ID and the incoming one."""
        self._request_id_token = _asgi_request_id.set(request_id)
        self._observability_id_token = _asgi_observability_id.set(None)
        self._incoming_observability_id_token = _asgi_incoming_observability_id.set(
            incoming_observability_id
        )

    def rebind_request_id(self, request_id: str) -> None:
        """Replace the request ID in the context."""
        _asgi_request_id.reset(self._request_id_token)
        self._request_id_token = _asgi_request_id.set(request_id)

    def reset(self) -> None:
        """Restore every context variable to its value before the request."""
        _asgi_request_id.reset(self._request_id_token)
        _asgi_observability_id.reset(self._observability_id_token)
        _asgi_incoming_observability_id.reset(self._incoming_observability_id_token)


class _NativeRouteTelemetry:
    """The observability record and migration log of one native-route request.

    Telemetry and migration logging must never fail the request, so every call
    to the runtime or the logger swallows its own errors.
    """

    def __init__(
        self,
        runtime: ObservabilityRuntime,
        request: Request,
        *,
        started_at: float,
        initial_route: str,
    ) -> None:
        """Track ``request``, which started at ``started_at`` on ``initial_route``."""
        self._runtime = runtime
        self._request = request
        self._started_at = started_at
        self._initial_route = initial_route
        self._request_id: str | None = None

    def begin(self, request_id: str, context_tokens: _RequestContextTokens) -> str:
        """Begin the runtime's request record and return the request ID to use.

        A request ID that the runtime assigns replaces ``request_id`` on the
        request and in its context.
        """
        # Telemetry must never fail the request.
        with contextlib.suppress(Exception):
            runtime_request_id = self._runtime.begin_request(
                headers={
                    **dict(self._request.headers),
                    REQUEST_ID_HEADER: request_id,
                },
                method=self._request.method,
                route=self._initial_route,
            )
            if isinstance(runtime_request_id, str) and runtime_request_id:
                request_id = runtime_request_id
                _bind_request_id(self._request, request_id)
                context_tokens.rebind_request_id(request_id)
        # Telemetry must never fail the request.
        with contextlib.suppress(Exception):
            self._runtime.set_context(
                request_id=request_id,
            )
        self._request_id = request_id
        return request_id

    def annotate_response(
        self,
        response: Response,
        observability_id: str | None,
    ) -> None:
        """Record the response's observability ID and add the runtime's headers."""
        if observability_id is not None:
            # Telemetry must never fail the request.
            with contextlib.suppress(Exception):
                # Route-level spans have completed at this point, so this
                # call applies the selected calculation identifier to the
                # still-current server request span.
                self._runtime.set_context(observability_id=observability_id)
        # Telemetry must never fail the request.
        with contextlib.suppress(Exception):
            for name, value in self._runtime.response_headers().items():
                response.headers[name] = value

    def log(self, status_code: int) -> None:
        """Log the served request in the migration request log."""
        # Migration logging must never fail the request.
        with contextlib.suppress(Exception):
            log_migration_request(
                ServedRequest(
                    request_id=self._request_id,
                    method=self._request.method,
                    path=self._request.url.path,
                    status_code=status_code,
                    started_at=self._started_at,
                    country_id=(
                        self._request.path_params.get("country_id")
                        or self._request.query_params.get("country_id")
                    ),
                    route_impl=RouteImplementation.FASTAPI_NATIVE,
                )
            )

    def finish(
        self,
        status_code: int,
        error: BaseException | None = None,
    ) -> None:
        """End the runtime's request record with its resolved route and status."""
        resolved_route = getattr(
            self._request.scope.get("route"), "path", self._initial_route
        )
        # Telemetry must never fail the request.
        with contextlib.suppress(Exception):
            self._runtime.update_request_route(resolved_route)
        # Telemetry must never fail the request.
        with contextlib.suppress(Exception):
            self._runtime.update_request_status(status_code)
        # Telemetry must never fail the request.
        with contextlib.suppress(Exception):
            self._runtime.end_request(
                status_code=status_code,
                error=error,
            )


async def _call_route(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    telemetry: _NativeRouteTelemetry | None,
) -> Response:
    """Call the route, recording a native route that raises as a server error."""
    try:
        return await call_next(request)
    except Exception as error:
        if telemetry is not None:
            telemetry.log(500)
            telemetry.finish(500, error)
        raise


def _finish_response(
    response: Response,
    request_id: str,
    telemetry: _NativeRouteTelemetry | None,
) -> Response:
    """Add the request and observability IDs to a response and record it."""
    response_observability_id = current_observability_id() or (
        normalize_observability_id(response.headers.get(OBSERVABILITY_ID_HEADER))
    )
    if telemetry is not None:
        telemetry.annotate_response(response, response_observability_id)
    _apply_request_id_header(response, request_id)
    if response_observability_id is not None:
        _apply_observability_id_header(response, response_observability_id)
    elif OBSERVABILITY_ID_HEADER in response.headers:
        del response.headers[OBSERVABILITY_ID_HEADER]
    if telemetry is not None:
        telemetry.log(response.status_code)
        telemetry.finish(response.status_code)
    return response


async def _serve_with_request_context(
    app: FastAPI,
    request_runtime: ObservabilityRuntime,
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Serve one request with its request ID, context and native-route telemetry."""
    started_at = time.time()
    request_id = request.headers.get(REQUEST_ID_HEADER) or generate_request_id()
    incoming_observability_id = normalize_observability_id(
        request.headers.get(OBSERVABILITY_ID_HEADER)
    )
    _bind_request_id(request, request_id)
    request.state.policyengine_observability_id = None
    context_tokens = _RequestContextTokens(request_id, incoming_observability_id)
    native_route_template = _native_route_template(app, request.scope)
    telemetry = None
    if native_route_template is not None:
        telemetry = _NativeRouteTelemetry(
            request_runtime,
            request,
            started_at=started_at,
            initial_route=native_route_template or request.url.path,
        )
        request_id = telemetry.begin(request_id, context_tokens)

    try:
        response = await _call_route(request, call_next, telemetry)
        return _finish_response(response, request_id, telemetry)
    finally:
        context_tokens.reset()


def _lifespan_with_shutdown(
    shutdown_callback: Callable[[], None] | None,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Build a lifespan that calls ``shutdown_callback``, if any, as the app stops."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if shutdown_callback is not None:
                shutdown_callback()

    return lifespan


async def _add_headers_to_unhandled_errors(
    request: Request,
    _error: Exception,
) -> Response:
    """Answer an unhandled error with a plain 500 that keeps the request IDs."""
    response = PlainTextResponse("Internal Server Error", status_code=500)
    request_id = getattr(
        request.state,
        "policyengine_request_id",
        request.headers.get(REQUEST_ID_HEADER) or generate_request_id(),
    )
    _apply_request_id_header(response, request_id)
    observability_id = current_observability_id()
    if observability_id is not None:
        _apply_observability_id_header(response, observability_id)
    return response


async def _typed_v2_request_validation_error(
    request: Request,
    error: RequestValidationError,
) -> Response:
    """Answer an invalid v2 request with the typed v2 error, and others as usual."""
    if request.url.path.startswith("/v2/"):
        return v2_error_response(422, "Invalid API v2 request")
    return await request_validation_exception_handler(request, error)


async def _oversized_v2_request(
    _request: Request,
    error: V2RequestTooLargeError,
) -> Response:
    """Answer an oversized v2 request body with the typed v2 error."""
    return v2_error_response(413, str(error))


async def _unauthenticated_v2_request(
    _request: Request,
    error: V2AuthenticationRequiredError,
) -> Response:
    """Answer a v2 request without a valid credential with a typed 401 challenge."""
    return v2_error_response(
        401,
        str(error),
        headers={"WWW-Authenticate": error.challenge},
    )


async def _forbidden_v2_request(
    _request: Request,
    error: V2PermissionDeniedError,
) -> Response:
    """Answer a v2 request the caller may not make with the typed 403 error."""
    return v2_error_response(403, str(error))


async def _unavailable_v2_authentication(
    _request: Request,
    error: V2AuthenticationUnavailableError,
) -> Response:
    """Answer a v2 request whose credential cannot be checked with a typed 503."""
    return v2_error_response(503, str(error))


def _register_request_context_middleware(
    app: FastAPI,
    request_runtime: ObservabilityRuntime,
) -> None:
    """Serve every request through its request context and telemetry."""

    @app.middleware("http")
    async def add_request_context_and_migration_logging(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        return await _serve_with_request_context(
            app,
            request_runtime,
            request,
            call_next,
        )


def _include_native_routers(
    app: FastAPI,
    route_settings: RouteImplementationSettings,
    dependencies: NativeRouteDependencies,
) -> None:
    """Include the always-native routers and those the settings select."""
    app.include_router(build_core_health_router(dependencies))
    app.include_router(build_v2_router(dependencies))
    if route_settings.health is RouteImplementation.FASTAPI_NATIVE:
        app.include_router(build_readiness_router(dependencies))
    if route_settings.metadata is RouteImplementation.FASTAPI_NATIVE:
        app.include_router(build_metadata_router(dependencies))


def create_asgi_app(
    wsgi_app: Any,  # noqa: ANN401  # Flask's WSGI signature and a2wsgi's WSGIApp stubs disagree
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

    app = FastAPI(
        title="PolicyEngine API",
        version=VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan_with_shutdown(shutdown_callback),
    )
    # compresslevel 4 instead of starlette's default 9: /us/metadata is ~70MB
    # raw, and level-9 compression inside the request costs seconds of CPU on
    # Cloud Run because it does not have an nginx sidecar to handle gzip.
    # Measured on the real payload: level 9 = 5.5s -> 9.0MB, level 4 = 0.7s ->
    # 9.9MB — 7.5x faster for ~10% larger output.
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=4)
    app.exception_handler(Exception)(_add_headers_to_unhandled_errors)
    app.exception_handler(RequestValidationError)(_typed_v2_request_validation_error)
    app.exception_handler(V2RequestTooLargeError)(_oversized_v2_request)
    app.exception_handler(V2AuthenticationRequiredError)(_unauthenticated_v2_request)
    app.exception_handler(V2PermissionDeniedError)(_forbidden_v2_request)
    app.exception_handler(V2AuthenticationUnavailableError)(
        _unavailable_v2_authentication
    )
    _register_request_context_middleware(app, request_runtime)
    _include_native_routers(app, route_settings, dependencies)

    app.mount("/", WSGIMiddleware(wsgi_app))
    # The public API already permits every web origin. Use the standard ASGI
    # implementation while preserving the existing reflected-origin response.
    return CORSMiddleware(
        app=app,
        allow_origin_regex=".*",
        allow_methods=["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"],
        allow_headers=["*"],
        expose_headers=[
            REQUEST_ID_HEADER,
            OBSERVABILITY_ID_HEADER,
            "WWW-Authenticate",
        ],
        allow_credentials=False,
        max_age=600,
    )
