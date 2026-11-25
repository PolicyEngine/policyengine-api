"""API v2 routes that serve dynamic parameters and their current-law values.

Dynamic parameters are the model assumptions a dynamic sets
(``policyengine_api.dynamic_parameters``). These routes read them and their
values only from their own tables (C1 · 50), apart from the policy parameter
routes (C1 · 46, Q4), and mirror those routes' queries, pages and errors. The
children route's tree is built on each request, with the stored labels of
the shared parameter nodes and the version's enum labels; there is no search
file for this category.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from policyengine_api.fastapi_routes.v2.metadata.query_support import (
    CatalogQueryDependency,
    DynamicParameterChildrenQueryDependency,
    ParameterCollectionQueryDependency,
    ParameterValueCollectionQueryDependency,
)
from policyengine_api.fastapi_routes.v2.metadata.response_models import (
    MetadataDynamicParameterChildPageResponse,
    MetadataDynamicParameterDetailResponse,
    MetadataDynamicParameterPageResponse,
    MetadataDynamicParameterValueDetailResponse,
    MetadataDynamicParameterValuePageResponse,
)
from policyengine_api.fastapi_routes.v2.metadata.route_support import (
    CURRENT_LAW_VALUE_ERROR_RESPONSES,
    METADATA_RESPONSES,
    CacheableMetadataRoute,
    read_resource,
    take_utc_instant_for_read,
)
from policyengine_api.services.v2.metadata.dynamic_parameters.types import (
    DynamicParameterTreeLevel,
)
from policyengine_api.services.v2.metadata.types import (
    ParameterFilter,
    ParameterValueFilter,
)

if TYPE_CHECKING:
    from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies


def build_v2_dynamic_parameter_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the v2 dynamic parameter, tree and current-law value routes.

    Each request opens and closes its own metadata reader, so building the
    router touches no database.
    """
    router = APIRouter(
        prefix="/v2",
        responses=METADATA_RESPONSES,
        route_class=CacheableMetadataRoute,
    )

    @router.get(
        "/dynamic-parameters",
        response_model=MetadataDynamicParameterPageResponse,
        summary="List dynamic parameters from a selected PolicyEngine.py catalog",
        description=(
            "Lists the model assumptions a dynamic sets, in name order, apart "
            "from policy parameters. A dynamic may set one whose economy or "
            "household flag is true."
        ),
    )
    def list_dynamic_parameters(
        query: ParameterCollectionQueryDependency,
    ) -> MetadataDynamicParameterPageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataDynamicParameterPageResponse,
            lambda reader: reader.dynamic_parameters.list_dynamic_parameters(
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
        "/dynamic-parameters/children",
        response_model=MetadataDynamicParameterChildPageResponse,
        responses=CURRENT_LAW_VALUE_ERROR_RESPONSES,
        summary="List one level of a catalog version's dynamic parameter tree",
        description=(
            "Lists the direct children of `parent_path` (the top level when "
            "empty: `gov`, plus `simulation` for the US). With `settable=true`, "
            "only the children a dynamic may set (a dynamic parameter whose "
            "economy or household flag is true, and every node above one), "
            "sorted by label, with child counts that count only those. The tree "
            "is built on each request with the policy tree's labels and order."
        ),
    )
    def list_dynamic_parameter_children(
        query: DynamicParameterChildrenQueryDependency,
    ) -> MetadataDynamicParameterChildPageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataDynamicParameterChildPageResponse,
            lambda reader: reader.dynamic_parameters.list_dynamic_parameter_children(
                query.country_id,
                query.policyengine_version,
                level=DynamicParameterTreeLevel(
                    parent_path=query.parent_path, settable=query.settable
                ),
                offset=query.offset,
                limit=query.limit,
            ),
        )

    @router.get(
        "/dynamic-parameters/{parameter_id}",
        response_model=MetadataDynamicParameterDetailResponse,
        summary="Get one dynamic parameter from a selected PolicyEngine.py catalog",
    )
    def get_dynamic_parameter(
        parameter_id: UUID,
        query: CatalogQueryDependency,
    ) -> MetadataDynamicParameterDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataDynamicParameterDetailResponse,
            lambda reader: reader.dynamic_parameters.get_dynamic_parameter(
                query.country_id,
                parameter_id,
                query.policyengine_version,
            ),
        )

    @router.get(
        "/dynamic-parameter-values",
        response_model=MetadataDynamicParameterValuePageResponse,
        responses=CURRENT_LAW_VALUE_ERROR_RESPONSES,
        summary="List current-law values of a catalog's dynamic parameters",
        description=(
            "Lists current-law values only: the values a dynamic sets are "
            "never listed. parameter_id is a dynamic parameter's ID."
        ),
    )
    def list_dynamic_parameter_values(
        request: Request,
        query: ParameterValueCollectionQueryDependency,
    ) -> MetadataDynamicParameterValuePageResponse | JSONResponse:
        # Current values are those in effect on the request's UTC day; the
        # read and the response's lifetime use the same instant.
        now = take_utc_instant_for_read(request) if query.current else None
        return read_resource(
            dependencies,
            MetadataDynamicParameterValuePageResponse,
            lambda reader: reader.dynamic_parameters.list_dynamic_parameter_values(
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
        "/dynamic-parameter-values/{value_id}",
        response_model=MetadataDynamicParameterValueDetailResponse,
        responses=CURRENT_LAW_VALUE_ERROR_RESPONSES,
        summary="Get one current-law value of a catalog's dynamic parameter",
    )
    def get_dynamic_parameter_value(
        value_id: UUID,
        query: CatalogQueryDependency,
    ) -> MetadataDynamicParameterValueDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataDynamicParameterValueDetailResponse,
            lambda reader: reader.dynamic_parameters.get_dynamic_parameter_value(
                query.country_id,
                value_id,
                query.policyengine_version,
            ),
        )

    return router
