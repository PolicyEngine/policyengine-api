"""Tax-benefit model, version, and variable preview routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from starlette.responses import JSONResponse

from policyengine_api.data.v2.catalog.schemas import (
    MetadataModelDetailResponse,
    MetadataModelPageResponse,
    MetadataModelSelectionResponse,
    MetadataModelVersionDetailResponse,
    MetadataModelVersionPageResponse,
    MetadataVariableDetailResponse,
    MetadataVariablePageResponse,
)
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.fastapi_routes.v2_metadata_common import (
    ERROR_RESPONSES,
    read_resource,
)


Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=500)]


def build_v2_metadata_model_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    router = APIRouter(prefix="/v2", responses=ERROR_RESPONSES)

    @router.get(
        "/tax-benefit-models",
        response_model=MetadataModelPageResponse,
        summary="List models for one PolicyEngine.py catalog",
    )
    def list_models(
        country_id: str,
        policyengine_version: str | None = None,
        offset: Offset = 0,
        limit: Limit = 100,
    ) -> MetadataModelPageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataModelPageResponse,
            lambda reader: reader.list_models(
                country_id,
                policyengine_version,
                offset=offset,
                limit=limit,
            ),
        )

    @router.get(
        "/tax-benefit-models/by-country/{country_id}",
        response_model=MetadataModelSelectionResponse,
        summary="Get a country model and selected PolicyEngine.py version",
    )
    def get_model_by_country(
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataModelSelectionResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataModelSelectionResponse,
            lambda reader: reader.get_model_by_country(
                country_id,
                policyengine_version,
            ),
        )

    @router.get(
        "/tax-benefit-models/{model_id}",
        response_model=MetadataModelDetailResponse,
        summary="Get one model from a selected PolicyEngine.py catalog",
    )
    def get_model(
        model_id: UUID,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataModelDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataModelDetailResponse,
            lambda reader: reader.get_model(
                country_id,
                model_id,
                policyengine_version,
            ),
        )

    @router.get(
        "/tax-benefit-model-versions",
        response_model=MetadataModelVersionPageResponse,
        summary="List selected PolicyEngine.py model versions",
    )
    def list_model_versions(
        country_id: str,
        policyengine_version: str | None = None,
        offset: Offset = 0,
        limit: Limit = 100,
    ) -> MetadataModelVersionPageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataModelVersionPageResponse,
            lambda reader: reader.list_model_versions(
                country_id,
                policyengine_version,
                offset=offset,
                limit=limit,
            ),
        )

    @router.get(
        "/tax-benefit-model-versions/{version_id}",
        response_model=MetadataModelVersionDetailResponse,
        summary="Get one selected PolicyEngine.py model version",
    )
    def get_model_version(
        version_id: UUID,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataModelVersionDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataModelVersionDetailResponse,
            lambda reader: reader.get_model_version(
                country_id,
                version_id,
                policyengine_version,
            ),
        )

    @router.get(
        "/variables",
        response_model=MetadataVariablePageResponse,
        summary="List variables from a selected PolicyEngine.py catalog",
    )
    def list_variables(
        country_id: str,
        policyengine_version: str | None = None,
        offset: Offset = 0,
        limit: Limit = 100,
        search: str | None = None,
    ) -> MetadataVariablePageResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataVariablePageResponse,
            lambda reader: reader.list_variables(
                country_id,
                policyengine_version,
                offset=offset,
                limit=limit,
                search=search,
            ),
        )

    @router.get(
        "/variables/{variable_id}",
        response_model=MetadataVariableDetailResponse,
        summary="Get one variable from a selected PolicyEngine.py catalog",
    )
    def get_variable(
        variable_id: UUID,
        country_id: str,
        policyengine_version: str | None = None,
    ) -> MetadataVariableDetailResponse | JSONResponse:
        return read_resource(
            dependencies,
            MetadataVariableDetailResponse,
            lambda reader: reader.get_variable(
                country_id,
                variable_id,
                policyengine_version,
            ),
        )

    return router
