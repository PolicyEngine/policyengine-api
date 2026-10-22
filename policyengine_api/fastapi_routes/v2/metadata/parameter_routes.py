"""API v2 parameter and canonical parameter-value routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import JSONResponse

from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.metadata.common import (
    DEPENDS_ON_UTC_DAY,
    ERROR_RESPONSES,
    CacheableMetadataRoute,
    read_resource,
)
from policyengine_api.fastapi_routes.v2.metadata.response_models import (
    MetadataParameterChildPageResponse,
    MetadataParameterDetailResponse,
    MetadataParameterPageResponse,
    MetadataParameterValueDetailResponse,
    MetadataParameterValuePageResponse,
)
from policyengine_api.query_parameters import (
    ParameterCollectionQuery,
    ParameterValueCollectionQuery,
)
from policyengine_api.services.v2.metadata.types import (
    ParameterFilter,
    ParameterValueFilter,
)

if TYPE_CHECKING:
    from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies

Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=500)]


ParameterCollectionQueryDependency = Annotated[
    ParameterCollectionQuery, Depends(query_dependency(ParameterCollectionQuery))
]
ParameterValueCollectionQueryDependency = Annotated[
    ParameterValueCollectionQuery,
    Depends(query_dependency(ParameterValueCollectionQuery)),
]


def build_v2_metadata_parameter_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the v2 parameter, parameter-tree and parameter-value routes.

    Each request opens and closes its own metadata reader, so building the
    router touches no database.
    """
    router = APIRouter(
        prefix="/v2",
        responses=ERROR_RESPONSES,
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
        request: Request,
        query: ParameterValueCollectionQueryDependency,
    ) -> MetadataParameterValuePageResponse | JSONResponse:
        # Current values are those in effect on the request's UTC day.
        setattr(request.state, DEPENDS_ON_UTC_DAY, query.current)
        return read_resource(
            dependencies,
            MetadataParameterValuePageResponse,
            lambda reader: reader.list_parameter_values(
                query.country_id,
                query.policyengine_version,
                value_filter=ParameterValueFilter(
                    parameter_id=query.parameter_id,
                    current=query.current,
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
