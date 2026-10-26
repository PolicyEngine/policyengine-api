"""API v2 tax-benefit model, version, and variable routes."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter
from starlette.responses import JSONResponse

from policyengine_api.fastapi_routes.v2.metadata.common import (
    METADATA_RESPONSES,
    PATH_COUNTRY_ERROR_RESPONSES,
    CacheableMetadataRoute,
    read_resource,
)
from policyengine_api.fastapi_routes.v2.metadata.query_dependencies import (
    CatalogPageQueryDependency,
    CatalogQueryDependency,
    CatalogVersionQueryDependency,
    VariableCollectionQueryDependency,
)
from policyengine_api.fastapi_routes.v2.metadata.response_models import (
    MetadataModelDetailResponse,
    MetadataModelPageResponse,
    MetadataModelSelectionResponse,
    MetadataModelVersionDetailResponse,
    MetadataModelVersionPageResponse,
    MetadataVariableDetailResponse,
    MetadataVariablePageResponse,
)

if TYPE_CHECKING:
    from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies


def build_v2_metadata_model_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the v2 tax-benefit model, model-version and variable routes.

    Each request opens and closes its own metadata reader, so building the
    router touches no database.
    """
    router = APIRouter(
        prefix="/v2",
        responses=METADATA_RESPONSES,
        route_class=CacheableMetadataRoute,
    )

    @router.get(
        "/tax-benefit-models",
        response_model=MetadataModelPageResponse,
        summary="List models for one PolicyEngine.py catalog",
    )
    def list_models(
        query: CatalogPageQueryDependency,
    ) -> MetadataModelPageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataModelPageResponse,
            lambda reader: reader.list_models(
                query.country_id,
                query.policyengine_version,
                offset=query.offset,
                limit=query.limit,
            ),
        )

    @router.get(
        "/tax-benefit-models/by-country/{country_id}",
        response_model=MetadataModelSelectionResponse,
        responses=PATH_COUNTRY_ERROR_RESPONSES,
        summary="Get a country model and selected PolicyEngine.py version",
    )
    def get_model_by_country(
        country_id: str,
        query: CatalogVersionQueryDependency,
    ) -> MetadataModelSelectionResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataModelSelectionResponse,
            lambda reader: reader.get_model_by_country(
                country_id,
                query.policyengine_version,
            ),
        )

    @router.get(
        "/tax-benefit-models/{model_id}",
        response_model=MetadataModelDetailResponse,
        summary="Get one model from a selected PolicyEngine.py catalog",
    )
    def get_model(
        model_id: UUID,
        query: CatalogQueryDependency,
    ) -> MetadataModelDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataModelDetailResponse,
            lambda reader: reader.get_model(
                query.country_id,
                model_id,
                query.policyengine_version,
            ),
        )

    @router.get(
        "/tax-benefit-model-versions",
        response_model=MetadataModelVersionPageResponse,
        summary="List selected PolicyEngine.py model versions",
    )
    def list_model_versions(
        query: CatalogPageQueryDependency,
    ) -> MetadataModelVersionPageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataModelVersionPageResponse,
            lambda reader: reader.list_model_versions(
                query.country_id,
                query.policyengine_version,
                offset=query.offset,
                limit=query.limit,
            ),
        )

    @router.get(
        "/tax-benefit-model-versions/{version_id}",
        response_model=MetadataModelVersionDetailResponse,
        summary="Get one selected PolicyEngine.py model version",
    )
    def get_model_version(
        version_id: UUID,
        query: CatalogQueryDependency,
    ) -> MetadataModelVersionDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataModelVersionDetailResponse,
            lambda reader: reader.get_model_version(
                query.country_id,
                version_id,
                query.policyengine_version,
            ),
        )

    @router.get(
        "/variables",
        response_model=MetadataVariablePageResponse,
        summary="List variables from a selected PolicyEngine.py catalog",
    )
    def list_variables(
        query: VariableCollectionQueryDependency,
    ) -> MetadataVariablePageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataVariablePageResponse,
            lambda reader: reader.list_variables(
                query.country_id,
                query.policyengine_version,
                offset=query.offset,
                limit=query.limit,
                search=query.search,
            ),
        )

    @router.get(
        "/variables/{variable_id}",
        response_model=MetadataVariableDetailResponse,
        summary="Get one variable from a selected PolicyEngine.py catalog",
    )
    def get_variable(
        variable_id: UUID,
        query: CatalogQueryDependency,
    ) -> MetadataVariableDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataVariableDetailResponse,
            lambda reader: reader.get_variable(
                query.country_id,
                variable_id,
                query.policyengine_version,
            ),
        )

    return router
