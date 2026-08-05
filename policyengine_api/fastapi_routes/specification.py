"""Native route for the static legacy OpenAPI specification."""

from __future__ import annotations

from fastapi import APIRouter
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from starlette.responses import JSONResponse


def build_specification_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the selectable native specification route."""
    router = APIRouter()

    @router.get(
        "/specification",
        response_class=JSONResponse,
        include_in_schema=False,
    )
    def specification() -> JSONResponse:
        return JSONResponse(dependencies.specification_provider())

    return router
