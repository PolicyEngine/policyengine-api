"""Request logging helpers for migration observability."""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

import flask

from policyengine_api.gcp_logging import logger
from policyengine_api.migration_flags import (
    ExplicitDatabaseSources,
    RouteImplementation,
    get_migration_log_context,
    infer_route_group,
)
from policyengine_api.observability.identifiers import (
    OBSERVABILITY_ID_HEADER,
    normalize_observability_id,
)
from policyengine_api.request_context import (
    REQUEST_ID_HEADER,
    generate_request_id,
)

if TYPE_CHECKING:
    from policyengine_observability import ObservabilityRuntime

V2_METADATA_RESOURCE_SEGMENTS = frozenset(
    {
        "datasets",
        "economy-options",
        "parameter-values",
        "parameters",
        "regions",
        "tax-benefit-model-versions",
        "tax-benefit-models",
        "variables",
    }
)
# Native v2 resources served from Supabase. The signed-in user resources
# (/v2/me*, /v2/user-*) keep their data only in Supabase, whatever the route
# group's configured v1 database flags say.
V2_SUPABASE_RESOURCE_SEGMENTS = frozenset(
    {
        "policies",
        "user-policies",
        "households",
        "user-households",
        "user-simulations",
        "user-reports",
        "me",
    }
)
# Signed-in user resources only store and read saved work. Their route groups
# (household, simulation, report, user_profile) also compute, but these
# requests never do, so they log no simulation flow or compute selection.
V2_USER_RESOURCE_SEGMENTS = frozenset(
    {"user-policies", "user-households", "user-simulations", "user-reports", "me"}
)
# /v2/household-calculations reads the stored household, policy and catalog
# from Supabase when submitting, stores nothing itself, and always computes on
# the Cloud Run Simulation Entrypoint's v2 workers, whatever the household
# route group's flags select.
V2_HOUSEHOLD_CALCULATION_SEGMENT = "household-calculations"
V2_HOUSEHOLD_CALCULATION_COMPUTE = {
    "sim_entrypoint": "cloud_run_simulation_entrypoint",
    "sim_compute": "v2_primary",
}
V2_RESOURCE_METHODS = frozenset({"GET", "POST", "PATCH", "DELETE"})
# A v2 resource path has at least the "v2" segment and the resource segment.
V2_RESOURCE_PATH_MINIMUM_SEGMENTS = 2


@dataclass(frozen=True)
class ServedRequest:
    """One served API request, as the migration request log records it."""

    request_id: str | None
    method: str
    path: str
    status_code: int
    started_at: float | None
    country_id: str | None = None
    route_impl: RouteImplementation | None = None


def _v2_resource_segment(path: str) -> str | None:
    """Return the resource segment of a ``/v2/<resource>`` path, or None."""
    segments = [segment for segment in path.strip("/").split("/") if segment]
    if len(segments) < V2_RESOURCE_PATH_MINIMUM_SEGMENTS or segments[0] != "v2":
        return None
    return segments[1]


def _is_v2_metadata_resource_read(method: str, path: str) -> bool:
    if method != "GET":
        return False
    return _v2_resource_segment(path) in V2_METADATA_RESOURCE_SEGMENTS


def _is_v2_supabase_resource(method: str, path: str) -> bool:
    return (
        method in V2_RESOURCE_METHODS
        and _v2_resource_segment(path) in V2_SUPABASE_RESOURCE_SEGMENTS
    )


def register_migration_request_logging(
    app: flask.Flask,
    *,
    runtime: ObservabilityRuntime | None = None,
) -> None:
    """Register request IDs and migration logging for Flask."""

    @app.before_request
    def set_request_migration_context() -> None:
        _set_request_migration_context(runtime)

    @app.after_request
    def log_request_migration_context(response: flask.Response) -> flask.Response:
        request_id, observability_id = _apply_request_identifiers(response)
        try:
            _record_request_migration_context(
                response,
                runtime,
                request_id=request_id,
                observability_id=observability_id,
            )
        except Exception:
            # A logging failure must not replace the response.
            with contextlib.suppress(Exception):
                app.logger.exception("Failed to log migration request context")
        return response


def _set_request_migration_context(runtime: ObservabilityRuntime | None) -> None:
    """Record the request's start time and identifiers on ``flask.g``.

    The request ID comes from the runtime's captured context, else the request
    header, else a new ID.
    """
    flask.g.request_started_at = time.time()
    try:
        captured = runtime.capture_context() if runtime is not None else {}
    except Exception:  # noqa: BLE001  # telemetry must never fail the request
        captured = {}
    flask.g.request_id = captured.get("request_id") or (
        flask.request.headers.get(REQUEST_ID_HEADER) or generate_request_id()
    )
    flask.g.incoming_observability_id = normalize_observability_id(
        flask.request.headers.get(OBSERVABILITY_ID_HEADER)
    )
    flask.g.observability_id = None
    if runtime is not None:
        # Telemetry must never fail the request.
        with contextlib.suppress(Exception):
            runtime.set_context(request_id=flask.g.request_id)


def _apply_request_identifiers(
    response: flask.Response,
) -> tuple[str | None, str | None]:
    """Add the request and observability IDs on ``flask.g`` to the response.

    Return both IDs; either is None when the request has none.
    """
    request_id = getattr(flask.g, "request_id", None)
    if request_id is not None:
        response.headers[REQUEST_ID_HEADER] = request_id
    observability_id = getattr(flask.g, "observability_id", None)
    if observability_id is not None:
        response.headers[OBSERVABILITY_ID_HEADER] = observability_id
    return request_id, observability_id


def _record_request_migration_context(
    response: flask.Response,
    runtime: ObservabilityRuntime | None,
    *,
    request_id: str | None,
    observability_id: str | None,
) -> None:
    """Record a Flask response's migration context.

    With a runtime, the context enriches the runtime's own request record;
    without one, it is logged as a migration request record.
    """
    country_id = (
        flask.request.view_args.get("country_id") if flask.request.view_args else None
    )
    if runtime is not None:
        runtime_context = {
            "country_id": country_id,
            **_migration_context(
                method=flask.request.method,
                path=flask.request.path,
                route_impl=RouteImplementation.FLASK_FALLBACK,
            ),
        }
        if observability_id is not None:
            runtime_context["observability_id"] = observability_id
        runtime.set_context(**runtime_context)
        return
    log_migration_request(
        ServedRequest(
            request_id=request_id,
            method=flask.request.method,
            path=flask.request.path,
            status_code=response.status_code,
            started_at=getattr(flask.g, "request_started_at", None),
            country_id=country_id,
            route_impl=RouteImplementation.FLASK_FALLBACK,
        )
    )


def log_migration_request(served_request: ServedRequest) -> None:
    """Log a migration-aware API request in the shared structured format."""
    elapsed_ms = None
    if served_request.started_at is not None:
        elapsed_ms = round((time.time() - served_request.started_at) * 1000, 2)

    migration_context = _migration_context(
        method=served_request.method,
        path=served_request.path,
        route_impl=served_request.route_impl,
    )

    logger.log_struct(
        {
            "message": "API request served",
            "request_id": served_request.request_id,
            "method": served_request.method,
            "path": served_request.path,
            "status_code": served_request.status_code,
            "latency_ms": elapsed_ms,
            "country_id": served_request.country_id,
            "migration": migration_context,
        },
        severity=(
            "INFO"
            if served_request.status_code < HTTPStatus.INTERNAL_SERVER_ERROR
            else "ERROR"
        ),
    )


def _migration_context(
    *,
    method: str,
    path: str,
    route_impl: RouteImplementation | None,
) -> dict[str, str | None]:
    route_group = infer_route_group(path)
    if _v2_resource_segment(path) == V2_HOUSEHOLD_CALCULATION_SEGMENT:
        context = get_migration_log_context(
            route_group,
            route_impl=route_impl,
            explicit_db_sources=ExplicitDatabaseSources(
                db_read_source="supabase" if method == "POST" else None
            ),
        )
        if "migration_flag_error" not in context:
            context.update(V2_HOUSEHOLD_CALCULATION_COMPUTE)
        return context
    is_v2_metadata_read = _is_v2_metadata_resource_read(method, path)
    is_v2_supabase_resource = _is_v2_supabase_resource(method, path)
    uses_explicit_v2_source = is_v2_metadata_read or is_v2_supabase_resource
    explicit_db_sources = ExplicitDatabaseSources(
        db_write_source=(
            "supabase" if is_v2_supabase_resource and method != "GET" else None
        ),
        db_read_source=(
            "supabase"
            if is_v2_metadata_read or (is_v2_supabase_resource and method == "GET")
            else None
        ),
    )
    return get_migration_log_context(
        route_group,
        route_impl=route_impl,
        explicit_db_sources=explicit_db_sources if uses_explicit_v2_source else None,
        include_compute=_v2_resource_segment(path) not in V2_USER_RESOURCE_SEGMENTS,
    )
