"""Request logging helpers for migration observability."""

from __future__ import annotations

import time
import uuid

import flask

from policyengine_api.gcp_logging import logger
from policyengine_api.migration_flags import (
    BACKEND_RESPONSE_HEADER,
    get_api_host_backend,
    get_migration_log_context,
    infer_route_group,
)


def register_migration_request_logging(app: flask.Flask) -> None:
    """Register no-op migration context logging on a Flask app."""

    @app.before_request
    def set_request_migration_context():
        flask.g.request_started_at = time.time()
        flask.g.request_id = (
            flask.request.headers.get("X-Request-ID") or uuid.uuid4().hex
        )

    @app.after_request
    def log_request_migration_context(response):
        response.headers[BACKEND_RESPONSE_HEADER] = get_api_host_backend()
        try:
            log_migration_request(
                request_id=getattr(flask.g, "request_id", None),
                method=flask.request.method,
                path=flask.request.path,
                status_code=response.status_code,
                started_at=getattr(flask.g, "request_started_at", None),
                country_id=flask.request.view_args.get("country_id")
                if flask.request.view_args
                else None,
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
) -> None:
    """Log a migration-aware API request in the shared structured format."""

    elapsed_ms = None
    if started_at is not None:
        elapsed_ms = round((time.time() - started_at) * 1000, 2)

    route_group = infer_route_group(path)
    migration_context = get_migration_log_context(route_group)

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
