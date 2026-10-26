"""API v2 routes that serve a catalog version in parts loaded on demand."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse, Response

from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.metadata.common import (
    ERROR_RESPONSES,
    CacheableMetadataRoute,
    read_resource,
    read_whole_version_resource,
)
from policyengine_api.fastapi_routes.v2.metadata.response_models import (
    MetadataCatalogParametersResponse,
    MetadataCatalogVariablesResponse,
    MetadataModelCatalogResponse,
    MetadataResourceSuccessResponse,
)
from policyengine_api.query_parameters import CatalogParameterQuery, CatalogQuery
from policyengine_api.services.v2.metadata.types import (
    MetadataCatalogVariablesResult,
    MetadataModelCatalogResult,
)

if TYPE_CHECKING:
    from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies

CatalogQueryDependency = Annotated[
    CatalogQuery, Depends(query_dependency(CatalogQuery))
]
CatalogParameterQueryDependency = Annotated[
    CatalogParameterQuery, Depends(query_dependency(CatalogParameterQuery))
]


def build_v2_model_catalog_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the routes that serve one catalog version in parts.

    Each request opens and closes its own metadata reader, so building the
    router touches no database.
    """
    router = APIRouter(
        prefix="/v2",
        responses=ERROR_RESPONSES,
        route_class=CacheableMetadataRoute,
    )

    @router.get(
        "/model-catalog",
        response_model=MetadataModelCatalogResponse,
        summary="Get the small parts of one PolicyEngine.py catalog version",
        description=(
            "Returns the selected catalog version's model, model version, "
            "entities, basic inputs, regions, logical input datasets and "
            "economy choices, which are empty lists for a catalog without "
            "regions. The result names the selected PolicyEngine.py version, "
            "so a client can request the version's other parts by that exact "
            "version; a response for a named version may be reused for a day."
        ),
    )
    def get_model_catalog(
        query: CatalogQueryDependency,
    ) -> MetadataResourceSuccessResponse[MetadataModelCatalogResult] | Response:
        return read_whole_version_resource(
            dependencies,
            "model-catalog",
            query,
            MetadataModelCatalogResponse,
            lambda reader: reader.get_model_catalog(
                query.country_id, query.policyengine_version
            ),
        )

    @router.get(
        "/model-catalog/variables",
        response_model=MetadataCatalogVariablesResponse,
        summary="Get every variable of one PolicyEngine.py catalog version",
        description=(
            "Returns all of the selected catalog version's variables in name "
            "order, in one response. Where a variable's adds or subtracts list "
            "comes from a parameter, part_parameter_values carries that "
            "parameter's current-law values by date, so a client can pick the "
            "list for any year."
        ),
    )
    def get_catalog_variables(
        query: CatalogQueryDependency,
    ) -> MetadataResourceSuccessResponse[MetadataCatalogVariablesResult] | Response:
        return read_whole_version_resource(
            dependencies,
            "model-catalog/variables",
            query,
            MetadataCatalogVariablesResponse,
            lambda reader: reader.get_catalog_variables(
                query.country_id, query.policyengine_version
            ),
        )

    @router.get(
        "/model-catalog/parameters",
        response_model=MetadataCatalogParametersResponse,
        summary="Get several parameters of one catalog version by name",
        description=(
            "Returns the named parameters (repeat name for each, at most 100) "
            "in name order, each with its economy and household flags and its "
            "current-law values by date, plus the stored labels of their "
            "ancestor nodes for breadcrumbs and the requested names the "
            "version has no parameter for. A client showing or editing a "
            "reform loads all of its parameters in this one request."
        ),
    )
    def get_catalog_parameters(
        query: CatalogParameterQueryDependency,
    ) -> MetadataCatalogParametersResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataCatalogParametersResponse,
            lambda reader: reader.get_catalog_parameters(
                query.country_id, query.policyengine_version, names=query.name
            ),
        )

    return router
