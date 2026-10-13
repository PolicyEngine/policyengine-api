"""Native FastAPI routes for the signed-in account resource (/v2/me).

``GET /v2/me`` provisions the caller's PolicyEngine user on first use, with
``primary_country`` taken from ``country_id``. Every route requires a user
bearer token; authentication is a router-level dependency.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse, Response

from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2AccountResourceService,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.errors import (
    V2ErrorResponse,
    V2RequestTooLargeError,
)
from policyengine_api.fastapi_routes.v2.me.request_models import (
    MAXIMUM_IMPORT_REQUEST_BYTES,
    AccountImportRequest,
    AccountPatchRequest,
)
from policyengine_api.fastapi_routes.v2.me.response_models import (
    MeDetailResponse,
    MeDetailResult,
    MeExportResponse,
    MeExportResult,
    MeImportResponse,
    MeImportResult,
    MeItem,
)
from policyengine_api.fastapi_routes.v2.user_resources import (
    USER_RESOURCE_ERROR_RESPONSES,
    user_resource_operation,
)
from policyengine_api.query_parameters import CountryQuery
from policyengine_api.services.v2.identity.types import UserPrincipal


async def enforce_import_request_size(request: Request) -> None:
    """Bound both declared and actual request bytes before service creation."""

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise V2RequestTooLargeError(
                "Import request Content-Length is invalid"
            ) from error
        if declared_length > MAXIMUM_IMPORT_REQUEST_BYTES:
            raise V2RequestTooLargeError("Import request body exceeds 1 MiB")
    if len(await request.body()) > MAXIMUM_IMPORT_REQUEST_BYTES:
        raise V2RequestTooLargeError("Import request body exceeds 1 MiB")


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2AccountResourceService]:
    if dependencies.v2_account_service_factory is not None:
        return dependencies.v2_account_service_factory
    from policyengine_api.fastapi_routes.dependencies import (
        _default_v2_account_service_factory,
    )

    return _default_v2_account_service_factory


def build_v2_me_router(dependencies: NativeRouteDependencies) -> APIRouter:
    """Build signed-in account routes without opening a connection."""

    require_user = dependencies.require_user
    router = APIRouter(
        prefix="/v2",
        responses=USER_RESOURCE_ERROR_RESPONSES,
        dependencies=[Depends(require_user)],
    )
    country_query = query_dependency(CountryQuery)
    service_factory = _service_factory(dependencies)

    @router.get(
        "/me",
        response_model=MeDetailResponse,
        summary="Read (and on first use provision) the signed-in user",
        description=(
            "Returns the PolicyEngine user for the bearer token, creating it on "
            "the first call with primary_country set from country_id."
        ),
    )
    def get_me(
        query: CountryQuery = Depends(country_query),
        principal: UserPrincipal = Depends(require_user),
    ) -> MeDetailResponse | JSONResponse:
        def read() -> MeDetailResponse:
            item = service_factory().get_account(
                principal=principal,
                country_id=query.country_id,
            )
            return MeDetailResponse(result=MeDetailResult(item=MeItem.from_read(item)))

        return user_resource_operation(read)

    @router.patch(
        "/me",
        response_model=MeDetailResponse,
        summary="Update the signed-in user's names or primary country",
    )
    def patch_me(
        body: AccountPatchRequest,
        query: CountryQuery = Depends(country_query),
        principal: UserPrincipal = Depends(require_user),
    ) -> MeDetailResponse | JSONResponse:
        def patch() -> MeDetailResponse:
            item = service_factory().update_account(
                principal=principal,
                country_id=query.country_id,
                account_input=body,
            )
            return MeDetailResponse(result=MeDetailResult(item=MeItem.from_read(item)))

        return user_resource_operation(patch)

    @router.delete(
        "/me",
        response_model=None,
        status_code=204,
        response_class=Response,
        responses={
            502: {
                "model": V2ErrorResponse,
                "description": (
                    "Account data was deleted but the Auth0 user could not be "
                    "removed; retrying is safe."
                ),
            }
        },
        summary="Delete the signed-in user and all of their saved records",
        description=(
            "Deletes the user's legacy user mappings, then the user (identities "
            "and associations cascade), then the Auth0 user when the Management "
            "API is configured."
        ),
    )
    def delete_me(
        query: CountryQuery = Depends(country_query),
        principal: UserPrincipal = Depends(require_user),
    ) -> Response | JSONResponse:
        def delete() -> Response:
            service_factory().delete_account(principal=principal)
            return Response(status_code=204)

        return user_resource_operation(delete)

    @router.get(
        "/me/export",
        response_model=MeExportResponse,
        summary="Export the signed-in user and every saved record",
        description="Covers every country, not only country_id.",
    )
    def export_me(
        query: CountryQuery = Depends(country_query),
        principal: UserPrincipal = Depends(require_user),
    ) -> MeExportResponse | JSONResponse:
        def export() -> MeExportResponse:
            result = service_factory().export_account(
                principal=principal,
                country_id=query.country_id,
            )
            return MeExportResponse(result=MeExportResult.from_export(result))

        return user_resource_operation(export)

    @router.post(
        "/me/imports",
        response_model=MeImportResponse,
        responses={
            413: {
                "model": V2ErrorResponse,
                "description": "The import body exceeds 1 MiB.",
            }
        },
        summary="Import browser-local saved records into the signed-in account",
        description=(
            "At most 500 items and 1 MiB. Idempotent on (user, client_ref): an "
            "existing client_ref in the same country returns its stored ID "
            "unchanged. Items with an unknown v1 reference, an invalid shape, or "
            "a client_ref the user already holds in another country are skipped "
            "and reported."
        ),
    )
    def import_records(
        body: AccountImportRequest,
        query: CountryQuery = Depends(country_query),
        principal: UserPrincipal = Depends(require_user),
        _size: None = Depends(enforce_import_request_size),
    ) -> MeImportResponse | JSONResponse:
        def import_() -> MeImportResponse:
            result = service_factory().import_records(
                principal=principal,
                country_id=query.country_id,
                import_input=body,
            )
            return MeImportResponse(result=MeImportResult.from_result(result))

        return user_resource_operation(import_)

    return router
