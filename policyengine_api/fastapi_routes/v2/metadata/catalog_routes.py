"""API v2 route serving a whole metadata catalog version in one response."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header
from starlette.responses import JSONResponse, Response

from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.metadata.common import (
    ERROR_RESPONSES,
    run_metadata_read,
)
from policyengine_api.fastapi_routes.v2.metadata.response_models import (
    MetadataCatalogResponse,
)
from policyengine_api.query_parameters import CatalogQuery

if TYPE_CHECKING:
    from policyengine_api.fastapi_routes.dependencies import (
        NativeRouteDependencies,
        V2MetadataResourceReader,
    )
    from policyengine_api.services.v2.metadata.types import MetadataCatalogDocument

METADATA_CATALOG_FORMAT = 2
"""Changes whenever the document's shape changes, so validators never match old bodies."""

RUNNING_CATALOG_MAX_AGE_SECONDS = 300
PINNED_CATALOG_MAX_AGE_SECONDS = 86_400


def catalog_entity_tag(document: MetadataCatalogDocument) -> str:
    """Return the quoted ETag naming a document's country, version and format."""
    return (
        f'"{document.country_id}:{document.policyengine_version}:'
        f'{METADATA_CATALOG_FORMAT}"'
    )


def _matches(if_none_match: str | None, entity_tag: str) -> bool:
    if if_none_match is None:
        return False
    candidates = {candidate.strip() for candidate in if_none_match.split(",")}
    return "*" in candidates or bool(
        {entity_tag, f"W/{entity_tag}"}.intersection(candidates)
    )


def catalog_response(
    document: MetadataCatalogDocument,
    *,
    pinned: bool,
    if_none_match: str | None,
) -> Response:
    """Serve the document, or 304 when the client already holds this version.

    A request that names its catalog version may be cached for a day; one that
    takes the running version is revalidated after five minutes, since the
    running version changes when the API deploys a new PolicyEngine.py.
    """
    max_age = (
        PINNED_CATALOG_MAX_AGE_SECONDS if pinned else RUNNING_CATALOG_MAX_AGE_SECONDS
    )
    entity_tag = catalog_entity_tag(document)
    headers = {"ETag": entity_tag, "Cache-Control": f"public, max-age={max_age}"}
    if _matches(if_none_match, entity_tag):
        return Response(status_code=304, headers=headers)
    return Response(
        content=document.body, media_type="application/json", headers=headers
    )


def build_v2_model_catalog_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the whole-catalog route; building it touches no database."""
    router = APIRouter(prefix="/v2", responses=ERROR_RESPONSES)
    catalog_query = query_dependency(CatalogQuery)

    @router.get(
        "/model-catalog",
        response_model=MetadataCatalogResponse,
        summary="Get every parameter node, parameter and variable of a catalog",
        description=(
            "Returns the selected PolicyEngine.py catalog's parameter nodes, "
            "parameters with their current-law values, and variables in one "
            "response, for clients that load the whole model at once. Name the "
            "catalog with policyengine_version to make the response cacheable for "
            "a day; the ETag supports conditional requests."
        ),
    )
    def get_model_catalog(
        query: CatalogQuery = Depends(catalog_query),
        if_none_match: str | None = Header(default=None),
    ) -> Response | JSONResponse:
        def read(reader: V2MetadataResourceReader) -> Response:
            return catalog_response(
                reader.get_model_catalog(query.country_id, query.policyengine_version),
                pinned=query.policyengine_version is not None,
                if_none_match=if_none_match,
            )

        return run_metadata_read(dependencies, read)

    return router
