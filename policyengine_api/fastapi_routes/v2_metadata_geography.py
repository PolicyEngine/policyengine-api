"""Dataset, region, and economy-option preview routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from starlette.responses import JSONResponse

from policyengine_api.data.v2.catalog.schemas import (
    MetadataDatasetDetailResponse,
    MetadataDatasetPageResponse,
    MetadataEconomyOptionsResponse,
    MetadataRegionDetailResponse,
    MetadataRegionPageResponse,
    MetadataRegionType,
)
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.fastapi_routes.v2_metadata_common import (
    ERROR_RESPONSES,
    read_resource,
)


Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=500)]


def build_v2_metadata_geography_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    router = APIRouter(prefix="/v2")

    @router.get(
        "/datasets",
        response_model=MetadataDatasetPageResponse,
        responses=ERROR_RESPONSES,
        summary="List logical inputs from a selected PolicyEngine.py catalog",
    )
    def list_datasets(
        country_id: str,
        policyengine_version: str | None = None,
        offset: Offset = 0,
        limit: Limit = 100,
    ) -> MetadataDatasetPageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataDatasetPageResponse,
            lambda reader: reader.list_datasets(
                country_id,
                policyengine_version,
                offset=offset,
                limit=limit,
            ),
        )

    @router.get(
        "/datasets/{dataset_id}",
        response_model=MetadataDatasetDetailResponse,
        responses=ERROR_RESPONSES,
        summary="Get one logical input from a selected PolicyEngine.py catalog",
    )
    def get_dataset(
        dataset_id: UUID,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataDatasetDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataDatasetDetailResponse,
            lambda reader: reader.get_dataset(
                country_id,
                dataset_id,
                policyengine_version,
            ),
        )

    @router.get(
        "/regions",
        response_model=MetadataRegionPageResponse,
        responses=ERROR_RESPONSES,
        summary="List regions from a selected PolicyEngine.py catalog",
    )
    def list_regions(
        country_id: str,
        policyengine_version: str | None = None,
        region_type: MetadataRegionType | None = None,
        offset: Offset = 0,
        limit: Limit = 100,
    ) -> MetadataRegionPageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataRegionPageResponse,
            lambda reader: reader.list_regions(
                country_id,
                policyengine_version,
                region_type=region_type.value if region_type is not None else None,
                offset=offset,
                limit=limit,
            ),
        )

    @router.get(
        "/regions/by-code/{region_code:path}",
        response_model=MetadataRegionDetailResponse,
        responses=ERROR_RESPONSES,
        summary="Get one region by code from a selected catalog",
    )
    def get_region_by_code(
        region_code: str,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataRegionDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataRegionDetailResponse,
            lambda reader: reader.get_region_by_code(
                country_id,
                region_code,
                policyengine_version,
            ),
        )

    @router.get(
        "/regions/{region_id}",
        response_model=MetadataRegionDetailResponse,
        responses=ERROR_RESPONSES,
        summary="Get one region from a selected PolicyEngine.py catalog",
    )
    def get_region(
        region_id: UUID,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataRegionDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataRegionDetailResponse,
            lambda reader: reader.get_region(
                country_id,
                region_id,
                policyengine_version,
            ),
        )

    @router.get(
        "/economy-options",
        response_model=MetadataEconomyOptionsResponse,
        responses=ERROR_RESPONSES,
        summary="Get compact economy-selection options from a selected catalog",
    )
    def get_economy_options(
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataEconomyOptionsResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataEconomyOptionsResponse,
            lambda reader: reader.get_economy_options(
                country_id,
                policyengine_version,
            ),
        )

    return router
