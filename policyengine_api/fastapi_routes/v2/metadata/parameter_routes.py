"""API v2 parameter and canonical parameter-value routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from starlette.responses import JSONResponse

from policyengine_api.fastapi_routes.v2.metadata.response_models import (
    MetadataParameterChildPageResponse,
    MetadataParameterDetailResponse,
    MetadataParameterPageResponse,
    MetadataParameterValueDetailResponse,
    MetadataParameterValuePageResponse,
)
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.fastapi_routes.v2.metadata.common import (
    ERROR_RESPONSES,
    read_resource,
)


Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=500)]


def build_v2_metadata_parameter_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    router = APIRouter(prefix="/v2", responses=ERROR_RESPONSES)

    @router.get(
        "/parameters",
        response_model=MetadataParameterPageResponse,
        summary="List parameters from a selected PolicyEngine.py catalog",
    )
    def list_parameters(
        country_id: str,
        policyengine_version: str | None = None,
        offset: Offset = 0,
        limit: Limit = 100,
        search: str | None = None,
    ) -> MetadataParameterPageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataParameterPageResponse,
            lambda reader: reader.list_parameters(
                country_id,
                policyengine_version,
                offset=offset,
                limit=limit,
                search=search,
            ),
        )

    @router.get(
        "/parameters/children",
        response_model=MetadataParameterChildPageResponse,
        summary="List direct children of one parameter path",
    )
    def list_parameter_children(
        country_id: str,
        parent_path: str = "",
        policyengine_version: str | None = None,
        offset: Offset = 0,
        limit: Limit = 100,
    ) -> MetadataParameterChildPageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataParameterChildPageResponse,
            lambda reader: reader.list_parameter_children(
                country_id,
                policyengine_version,
                parent_path=parent_path,
                offset=offset,
                limit=limit,
            ),
        )

    @router.get(
        "/parameters/{parameter_id}",
        response_model=MetadataParameterDetailResponse,
        summary="Get one parameter from a selected PolicyEngine.py catalog",
    )
    def get_parameter(
        parameter_id: UUID,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataParameterDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataParameterDetailResponse,
            lambda reader: reader.get_parameter(
                country_id,
                parameter_id,
                policyengine_version,
            ),
        )

    @router.get(
        "/parameter-values",
        response_model=MetadataParameterValuePageResponse,
        summary="List canonical values from a selected PolicyEngine.py catalog",
    )
    def list_parameter_values(
        country_id: str,
        policyengine_version: str | None = None,
        parameter_id: UUID | None = None,
        current: bool = False,
        offset: Offset = 0,
        limit: Limit = 100,
    ) -> MetadataParameterValuePageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataParameterValuePageResponse,
            lambda reader: reader.list_parameter_values(
                country_id,
                policyengine_version,
                parameter_id=parameter_id,
                current=current,
                offset=offset,
                limit=limit,
            ),
        )

    @router.get(
        "/parameter-values/{value_id}",
        response_model=MetadataParameterValueDetailResponse,
        summary="Get one canonical value from a selected PolicyEngine.py catalog",
    )
    def get_parameter_value(
        value_id: UUID,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataParameterValueDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataParameterValueDetailResponse,
            lambda reader: reader.get_parameter_value(
                country_id,
                value_id,
                policyengine_version,
            ),
        )

    return router
