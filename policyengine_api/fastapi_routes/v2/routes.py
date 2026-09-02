"""Compose the native API v2 policy and metadata routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.fastapi_routes.v2.errors import V2ErrorResponse
from policyengine_api.fastapi_routes.v2.metadata.geography_routes import (
    build_v2_metadata_geography_router,
)
from policyengine_api.fastapi_routes.v2.metadata.model_routes import (
    build_v2_metadata_model_router,
)
from policyengine_api.fastapi_routes.v2.metadata.parameter_routes import (
    build_v2_metadata_parameter_router,
)
from policyengine_api.fastapi_routes.v2.policies.routes import build_v2_policy_router
from policyengine_api.fastapi_routes.v2.user_policies.routes import (
    build_v2_user_policy_router,
)


def build_v2_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build isolated resource routes without loading v2 configuration."""

    router = APIRouter()
    router.include_router(build_v2_user_policy_router(dependencies))
    router.include_router(build_v2_policy_router(dependencies))
    router.include_router(build_v2_metadata_model_router(dependencies))
    router.include_router(build_v2_metadata_parameter_router(dependencies))
    router.include_router(build_v2_metadata_geography_router(dependencies))

    @router.get(
        "/v2/openapi.json",
        include_in_schema=False,
        summary="OpenAPI document for dormant v2 metadata resources",
    )
    def v2_preview_openapi(request: Request) -> JSONResponse:
        schema = request.app.openapi()
        preview_schema = {
            **schema,
            "paths": {
                path: operation
                for path, operation in schema.get("paths", {}).items()
                if path.startswith("/v2/")
            },
        }
        return JSONResponse(preview_schema)

    @router.get(
        "/v2",
        response_model=V2ErrorResponse,
        status_code=404,
        include_in_schema=False,
    )
    def unsupported_v2_root() -> V2ErrorResponse:
        return V2ErrorResponse(message="API v2 resource was not found")

    @router.api_route(
        "/v2",
        methods=["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        response_model=V2ErrorResponse,
        status_code=405,
        include_in_schema=False,
    )
    def unsupported_v2_root_method() -> V2ErrorResponse:
        return V2ErrorResponse(message="API v2 resource does not support this method")

    @router.get(
        "/v2/{resource_path:path}",
        response_model=V2ErrorResponse,
        status_code=404,
        include_in_schema=False,
    )
    def unsupported_resource(resource_path: str) -> V2ErrorResponse:
        return V2ErrorResponse(
            message=f"API v2 resource {resource_path!r} was not found"
        )

    @router.api_route(
        "/v2/{resource_path:path}",
        methods=["POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        response_model=V2ErrorResponse,
        status_code=405,
        include_in_schema=False,
    )
    def unsupported_method(resource_path: str) -> V2ErrorResponse:
        return V2ErrorResponse(
            message=f"API v2 resource {resource_path!r} does not support this method"
        )

    return router
