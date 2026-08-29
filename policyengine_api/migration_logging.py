"""Request logging helpers for migration observability."""

from __future__ import annotations

import time

import flask
from policyengine_api.gcp_logging import logger
from policyengine_api.migration_flags import (
    BACKEND_RESPONSE_HEADER,
    RouteImplementation,
    get_api_host_backend,
    get_migration_log_context,
    infer_route_group,
)
from policyengine_api.request_context import (
    REQUEST_ID_HEADER,
    generate_request_id,
)


V2_METADATA_PREVIEW_READ_PATHS = frozenset(
    {
        "/v2/us/metadata",
        "/v2/uk/metadata",
    }
)


def register_migration_request_logging(app: flask.Flask) -> None:
    """Register request IDs, backend headers, and migration logging for Flask."""

    @app.before_request
    def set_request_migration_context():
        flask.g.request_started_at = time.time()
        flask.g.request_id = (
            flask.request.headers.get(REQUEST_ID_HEADER) or generate_request_id()
        )

    @app.after_request
    def log_request_migration_context(response):
        response.headers[BACKEND_RESPONSE_HEADER] = get_api_host_backend()
        request_id = getattr(flask.g, "request_id", None)
        if request_id is not None:
            response.headers[REQUEST_ID_HEADER] = request_id
        try:
            log_migration_request(
                request_id=request_id,
                method=flask.request.method,
                path=flask.request.path,
                status_code=response.status_code,
                started_at=getattr(flask.g, "request_started_at", None),
                country_id=flask.request.view_args.get("country_id")
                if flask.request.view_args
                else None,
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

    route_group = infer_route_group(path)
    is_v2_metadata_read = method == "GET" and path in V2_METADATA_PREVIEW_READ_PATHS
    migration_context = get_migration_log_context(
        route_group,
        route_impl=route_impl,
        use_configured_db_sources=not is_v2_metadata_read,
        db_read_source="supabase" if is_v2_metadata_read else None,
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
