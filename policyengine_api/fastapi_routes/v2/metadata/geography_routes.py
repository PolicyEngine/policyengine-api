"""API v2 dataset, region, and economy-option routes."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter
from starlette.responses import JSONResponse

from policyengine_api.fastapi_routes.v2.metadata.common import (
    ERROR_RESPONSES,
    CacheableMetadataRoute,
    read_resource,
)
from policyengine_api.fastapi_routes.v2.metadata.query_dependencies import (
    CatalogPageQueryDependency,
    CatalogQueryDependency,
    RegionCollectionQueryDependency,
)
from policyengine_api.fastapi_routes.v2.metadata.response_models import (
    MetadataDatasetDetailResponse,
    MetadataDatasetPageResponse,
    MetadataEconomyOptionsResponse,
    MetadataRegionDetailResponse,
    MetadataRegionPageResponse,
)

if TYPE_CHECKING:
    from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies


def build_v2_metadata_geography_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the v2 dataset, region and economy-option routes.

    Each request opens and closes its own metadata reader, so building the
    router touches no database.
    """
    router = APIRouter(
        prefix="/v2",
        responses=ERROR_RESPONSES,
        route_class=CacheableMetadataRoute,
    )

    @router.get(
        "/datasets",
        response_model=MetadataDatasetPageResponse,
        summary="List logical inputs from a selected PolicyEngine.py catalog",
    )
    def list_datasets(
        query: CatalogPageQueryDependency,
    ) -> MetadataDatasetPageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataDatasetPageResponse,
            lambda reader: reader.list_datasets(
                query.country_id,
                query.policyengine_version,
                offset=query.offset,
                limit=query.limit,
            ),
        )

    @router.get(
        "/datasets/{dataset_id}",
        response_model=MetadataDatasetDetailResponse,
        summary="Get one logical input from a selected PolicyEngine.py catalog",
    )
    def get_dataset(
        dataset_id: UUID,
        query: CatalogQueryDependency,
    ) -> MetadataDatasetDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataDatasetDetailResponse,
            lambda reader: reader.get_dataset(
                query.country_id,
                dataset_id,
                query.policyengine_version,
            ),
        )

    @router.get(
        "/regions",
        response_model=MetadataRegionPageResponse,
        summary="List regions from a selected PolicyEngine.py catalog",
    )
    def list_regions(
        query: RegionCollectionQueryDependency,
    ) -> MetadataRegionPageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataRegionPageResponse,
            lambda reader: reader.list_regions(
                query.country_id,
                query.policyengine_version,
                region_type=(
                    None if query.region_type is None else query.region_type.value
                ),
                offset=query.offset,
                limit=query.limit,
            ),
        )

    @router.get(
        "/regions/by-code/{region_code:path}",
        response_model=MetadataRegionDetailResponse,
        summary="Get one region by code from a selected catalog",
    )
    def get_region_by_code(
        region_code: str,
        query: CatalogQueryDependency,
    ) -> MetadataRegionDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataRegionDetailResponse,
            lambda reader: reader.get_region_by_code(
                query.country_id,
                region_code,
                query.policyengine_version,
            ),
        )

    @router.get(
        "/regions/{region_id}",
        response_model=MetadataRegionDetailResponse,
        summary="Get one region from a selected PolicyEngine.py catalog",
    )
    def get_region(
        region_id: UUID,
        query: CatalogQueryDependency,
    ) -> MetadataRegionDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataRegionDetailResponse,
            lambda reader: reader.get_region(
                query.country_id,
                region_id,
                query.policyengine_version,
            ),
        )

    @router.get(
        "/economy-options",
        response_model=MetadataEconomyOptionsResponse,
        summary="Get compact economy-selection options from a selected catalog",
    )
    def get_economy_options(
        query: CatalogQueryDependency,
    ) -> MetadataEconomyOptionsResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataEconomyOptionsResponse,
            lambda reader: reader.get_economy_options(
                query.country_id,
                query.policyengine_version,
            ),
        )

    return router
