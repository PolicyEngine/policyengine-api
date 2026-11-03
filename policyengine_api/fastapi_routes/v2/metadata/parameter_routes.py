"""API v2 parameter and canonical parameter-value routes."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from policyengine_api.fastapi_routes.v2.metadata.common import (
    METADATA_RESPONSES,
    CacheableMetadataRoute,
    read_resource,
    take_utc_instant_for_read,
)
from policyengine_api.fastapi_routes.v2.metadata.query_dependencies import (
    CatalogQueryDependency,
    ParameterChildrenQueryDependency,
    ParameterCollectionQueryDependency,
    ParameterValueCollectionQueryDependency,
)
from policyengine_api.fastapi_routes.v2.metadata.response_models import (
    MetadataParameterChildPageResponse,
    MetadataParameterDetailResponse,
    MetadataParameterPageResponse,
    MetadataParameterValueDetailResponse,
    MetadataParameterValuePageResponse,
)
from policyengine_api.services.v2.metadata.types import (
    ParameterFilter,
    ParameterValueFilter,
)

if TYPE_CHECKING:
    from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies


def build_v2_metadata_parameter_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the v2 parameter, parameter-tree and parameter-value routes.

    Each request opens and closes its own metadata reader, so building the
    router touches no database.
    """
    router = APIRouter(
        prefix="/v2",
        responses=METADATA_RESPONSES,
        route_class=CacheableMetadataRoute,
    )

    @router.get(
        "/parameters",
        response_model=MetadataParameterPageResponse,
        summary="List parameters from a selected PolicyEngine.py catalog",
    )
    def list_parameters(
        query: ParameterCollectionQueryDependency,
    ) -> MetadataParameterPageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataParameterPageResponse,
            lambda reader: reader.list_parameters(
                query.country_id,
                query.policyengine_version,
                offset=query.offset,
                limit=query.limit,
                parameter_filter=ParameterFilter(
                    search=query.search,
                    names=None if query.name is None else tuple(query.name),
                ),
            ),
        )

    @router.get(
        "/parameters/children",
        response_model=MetadataParameterChildPageResponse,
        summary="List direct children of one parameter path",
    )
    def list_parameter_children(
        query: ParameterChildrenQueryDependency,
    ) -> MetadataParameterChildPageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataParameterChildPageResponse,
            lambda reader: reader.list_parameter_children(
                query.country_id,
                query.policyengine_version,
                parent_path=query.parent_path,
                offset=query.offset,
                limit=query.limit,
            ),
        )

    @router.get(
        "/parameters/{parameter_id}",
        response_model=MetadataParameterDetailResponse,
        summary="Get one parameter from a selected PolicyEngine.py catalog",
    )
    def get_parameter(
        parameter_id: UUID,
        query: CatalogQueryDependency,
    ) -> MetadataParameterDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataParameterDetailResponse,
            lambda reader: reader.get_parameter(
                query.country_id,
                parameter_id,
                query.policyengine_version,
            ),
        )

    @router.get(
        "/parameter-values",
        response_model=MetadataParameterValuePageResponse,
        summary="List canonical values from a selected PolicyEngine.py catalog",
    )
    def list_parameter_values(
        request: Request,
        query: ParameterValueCollectionQueryDependency,
    ) -> MetadataParameterValuePageResponse | JSONResponse:
        # Current values are those in effect on the request's UTC day; the
        # read and the response's lifetime use the same instant.
        now = take_utc_instant_for_read(request) if query.current else None
        return read_resource(
            dependencies,
            MetadataParameterValuePageResponse,
            lambda reader: reader.list_parameter_values(
                query.country_id,
                query.policyengine_version,
                value_filter=ParameterValueFilter(
                    parameter_id=query.parameter_id,
                    current=query.current,
                    now=now,
                    parameter_names=(
                        None
                        if query.parameter_name is None
                        else tuple(query.parameter_name)
                    ),
                ),
                offset=query.offset,
                limit=query.limit,
            ),
        )

    @router.get(
        "/parameter-values/{value_id}",
        response_model=MetadataParameterValueDetailResponse,
        summary="Get one canonical value from a selected PolicyEngine.py catalog",
    )
    def get_parameter_value(
        value_id: UUID,
        query: CatalogQueryDependency,
    ) -> MetadataParameterValueDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataParameterValueDetailResponse,
            lambda reader: reader.get_parameter_value(
                query.country_id,
                value_id,
                query.policyengine_version,
            ),
        )

    return router
