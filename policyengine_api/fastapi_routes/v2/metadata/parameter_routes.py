"""API v2 parameter and canonical parameter-value routes."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse, Response

from policyengine_api.fastapi_routes.v2.metadata.common import (
    METADATA_RESPONSES,
    PARAMETER_SEARCH_FILE_ERROR_RESPONSES,
    PARAMETER_TREE_ERROR_RESPONSES,
    CacheableMetadataRoute,
    names_entity_tag,
    read_resource,
    run_metadata_read,
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
    MetadataParameterSearchFileContent,
    MetadataParameterValueDetailResponse,
    MetadataParameterValuePageResponse,
)
from policyengine_api.fastapi_routes.v2.metadata.search_file_response import (
    SEARCH_FILE_RESPONSE_HEADERS,
    parameter_search_file_response,
    search_file_entity_tag,
)
from policyengine_api.services.v2.metadata.types import (
    ParameterFilter,
    ParameterTreeLevel,
    ParameterValueFilter,
)

if TYPE_CHECKING:
    from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
    from policyengine_api.query_parameters import CatalogQuery


def _serve_parameter_search_file(
    dependencies: NativeRouteDependencies,
    request: Request,
    query: CatalogQuery,
) -> Response:
    """Serve the selected version's search file in the encoding it accepts.

    A request that revalidates a copy (If-None-Match) first reads only the
    stored hash, so a match is answered with 304 without loading the file.
    """
    accept_encoding = request.headers.get("accept-encoding")
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None:
        content_sha256 = run_metadata_read(
            dependencies,
            lambda reader: reader.get_parameter_search_file_hash(
                query.country_id, query.policyengine_version
            ),
        )
        if isinstance(content_sha256, JSONResponse):
            return content_sha256
        entity_tag = search_file_entity_tag(
            content_sha256, accept_encoding=accept_encoding
        )
        if names_entity_tag(if_none_match, entity_tag):
            # The route class answers a 200 whose ETag the request names
            # with 304, so the file itself is never read.
            return Response(headers={"ETag": entity_tag})
    result = run_metadata_read(
        dependencies,
        lambda reader: reader.get_parameter_search_file(
            query.country_id, query.policyengine_version
        ),
    )
    if isinstance(result, JSONResponse):
        return result
    return parameter_search_file_response(result, accept_encoding=accept_encoding)


def build_v2_metadata_parameter_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build the v2 parameter, parameter-tree, search-file and parameter-value routes.

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
        responses=PARAMETER_TREE_ERROR_RESPONSES,
        summary="List one level of a catalog version's parameter tree",
        description=(
            "Lists the direct children of `parent_path` (the top level when "
            "empty). With `reform_changeable=true`, only the children a reform "
            "can change, sorted by label, with child counts that count only "
            "those. Invalid query parameters return 422, including a malformed "
            "policyengine_version, an unsupported country, and an unknown or "
            "repeated parameter. A catalog version without a tree (publication "
            "writes trees only for the versions it publishes and for the "
            "installed version with catalog format 2) returns 503 with a "
            "message naming it."
        ),
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
                level=ParameterTreeLevel(
                    parent_path=query.parent_path,
                    reform_changeable=query.reform_changeable,
                ),
                offset=query.offset,
                limit=query.limit,
            ),
        )

    @router.get(
        "/parameters/search-file",
        response_model=None,
        response_class=Response,
        responses={
            200: {
                "model": MetadataParameterSearchFileContent,
                "description": (
                    "The catalog version's parameter search file, gzip-encoded "
                    "when the request accepts gzip."
                ),
                "headers": SEARCH_FILE_RESPONSE_HEADERS,
            },
            **PARAMETER_SEARCH_FILE_ERROR_RESPONSES,
        },
        summary="Get a catalog version's parameter search file",
    )
    def get_parameter_search_file(
        request: Request,
        query: CatalogQueryDependency,
    ) -> Response:
        return _serve_parameter_search_file(dependencies, request, query)

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
