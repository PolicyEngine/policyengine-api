"""Request logging helpers for migration observability."""

from __future__ import annotations

import time

import flask
from policyengine_observability import ObservabilityRuntime
from policyengine_api.gcp_logging import logger
from policyengine_api.migration_flags import (
    RouteImplementation,
    get_migration_log_context,
    infer_route_group,
)
from policyengine_api.request_context import (
    REQUEST_ID_HEADER,
    generate_request_id,
    resolve_observability_id,
)
from policyengine_api.observability.identifiers import OBSERVABILITY_ID_HEADER


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
V2_POLICY_RESOURCE_SEGMENTS = frozenset({"policies", "user-policies"})
V2_HOUSEHOLD_RESOURCE_SEGMENTS = frozenset({"households", "user-households"})


def _is_v2_metadata_resource_read(method: str, path: str) -> bool:
    if method != "GET":
        return False
    segments = [segment for segment in path.strip("/").split("/") if segment]
    return (
        len(segments) >= 2
        and segments[0] == "v2"
        and segments[1] in V2_METADATA_RESOURCE_SEGMENTS
    )


def _is_v2_policy_resource(method: str, path: str) -> bool:
    if method not in {"GET", "POST", "PATCH", "DELETE"}:
        return False
    segments = [segment for segment in path.strip("/").split("/") if segment]
    return (
        len(segments) >= 2
        and segments[0] == "v2"
        and segments[1] in V2_POLICY_RESOURCE_SEGMENTS
    )


def _is_v2_household_resource(method: str, path: str) -> bool:
    if method not in {"GET", "POST", "PATCH", "DELETE"}:
        return False
    segments = [segment for segment in path.strip("/").split("/") if segment]
    return (
        len(segments) >= 2
        and segments[0] == "v2"
        and segments[1] in V2_HOUSEHOLD_RESOURCE_SEGMENTS
    )


def register_migration_request_logging(
    app: flask.Flask,
    *,
    runtime: ObservabilityRuntime | None = None,
) -> None:
    """Register request IDs and migration logging for Flask."""

    @app.before_request
    def set_request_migration_context():
        flask.g.request_started_at = time.time()
        try:
            captured = runtime.capture_context() if runtime is not None else {}
        except Exception:
            captured = {}
        flask.g.request_id = captured.get("request_id") or (
            flask.request.headers.get(REQUEST_ID_HEADER) or generate_request_id()
        )
        flask.g.observability_id = resolve_observability_id(
            captured.get("observability_id")
            or flask.request.headers.get(OBSERVABILITY_ID_HEADER)
        )
        if runtime is not None:
            try:
                runtime.set_context(
                    request_id=flask.g.request_id,
                    observability_id=flask.g.observability_id,
                )
            except Exception:
                pass

    @app.after_request
    def log_request_migration_context(response):
        request_id = getattr(flask.g, "request_id", None)
        if request_id is not None:
            response.headers[REQUEST_ID_HEADER] = request_id
        observability_id = getattr(flask.g, "observability_id", None)
        if observability_id is not None:
            response.headers[OBSERVABILITY_ID_HEADER] = observability_id
        try:
            country_id = (
                flask.request.view_args.get("country_id")
                if flask.request.view_args
                else None
            )
            if runtime is not None:
                runtime.set_context(
                    country_id=country_id,
                    **_migration_context(
                        method=flask.request.method,
                        path=flask.request.path,
                        route_impl=RouteImplementation.FLASK_FALLBACK,
                    ),
                )
            else:
                log_migration_request(
                    request_id=request_id,
                    method=flask.request.method,
                    path=flask.request.path,
                    status_code=response.status_code,
                    started_at=getattr(flask.g, "request_started_at", None),
                    country_id=country_id,
                    route_impl=RouteImplementation.FLASK_FALLBACK,
                )
        except Exception:
            try:
                app.logger.exception("Failed to log migration request context")
            except Exception:
                pass
        return response


def log_migration_request(
    *,
    request_id: str | None,
    method: str,
    path: str,
    status_code: int,
    started_at: float | None,
    country_id: str | None = None,
    route_impl: RouteImplementation | None = None,
) -> None:
    """Log a migration-aware API request in the shared structured format."""

    elapsed_ms = None
    if started_at is not None:
        elapsed_ms = round((time.time() - started_at) * 1000, 2)

    migration_context = _migration_context(
        method=method,
        path=path,
        route_impl=route_impl,
    )

    logger.log_struct(
        {
            "message": "API request served",
            "request_id": request_id,
            "method": method,
            "path": path,
            "status_code": status_code,
            "latency_ms": elapsed_ms,
            "country_id": country_id,
            "migration": migration_context,
        },
        severity="INFO" if status_code < 500 else "ERROR",
    )


def _migration_context(
    *,
    method: str,
    path: str,
    route_impl: RouteImplementation | None,
) -> dict[str, str | None]:
    route_group = infer_route_group(path)
    is_v2_metadata_read = _is_v2_metadata_resource_read(method, path)
    is_v2_policy_resource = _is_v2_policy_resource(method, path)
    is_v2_household_resource = _is_v2_household_resource(method, path)
    uses_explicit_v2_source = (
        is_v2_metadata_read or is_v2_policy_resource or is_v2_household_resource
    )
    return get_migration_log_context(
        route_group,
        route_impl=route_impl,
        use_configured_db_sources=not uses_explicit_v2_source,
        db_write_source=(
            "supabase"
            if (is_v2_policy_resource or is_v2_household_resource)
            and method in {"POST", "PATCH", "DELETE"}
            else None
        ),
        db_read_source=(
            "supabase"
            if is_v2_metadata_read
            or (is_v2_policy_resource or is_v2_household_resource)
            and method == "GET"
            else None
        ),
    )
