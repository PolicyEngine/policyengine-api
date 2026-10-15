"""Native FastAPI routes for the current user's account resource (/v2/me).

A signed-in caller's standard user is provisioned on first use, with
``primary_country`` taken from ``country_id``. A signed-out browser's
unauthenticated user exists only after its first saved record, so reading
an absent one returns 404 and exporting it returns nothing. Every route
requires a credential; authentication is a router-level dependency.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from starlette.responses import JSONResponse, Response

from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2AccountResourceService,
    _default_v2_account_service_factory,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.errors import V2ErrorResponse
from policyengine_api.fastapi_routes.v2.me.request_models import (
    AccountPatchRequest,
)
from policyengine_api.fastapi_routes.v2.me.response_models import (
    MeDetailResponse,
    MeDetailResult,
    MeExportResponse,
    MeExportResult,
    MeItem,
    MeUpgradeResponse,
    MeUpgradeResult,
)
from policyengine_api.fastapi_routes.v2.user_auth import require_signed_in_principal
from policyengine_api.fastapi_routes.v2.user_resources import (
    USER_RESOURCE_ERROR_RESPONSES,
    enforce_user_write_request_size,
    user_resource_operation,
)
from policyengine_api.libs.user_auth import (
    CANONICAL_UUID_PATTERN,
    UNAUTHENTICATED_USER_HEADER,
)
from policyengine_api.query_parameters import CountryQuery
from policyengine_api.services.v2.identity.types import (
    AccountPrincipal,
    UserPrincipal,
)

CountryQueryDependency = Annotated[
    CountryQuery, Depends(query_dependency(CountryQuery))
]


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2AccountResourceService]:
    if dependencies.v2_account_service_factory is not None:
        return dependencies.v2_account_service_factory
    return _default_v2_account_service_factory


def _signed_in_user_dependency(
    require_user: Callable[..., AccountPrincipal],
) -> Callable[..., UserPrincipal]:
    """Build a dependency that admits only a signed-in principal of ``require_user``."""

    def require_signed_in_user(
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> UserPrincipal:
        return require_signed_in_principal(principal)

    return require_signed_in_user


def _upgrade_account(
    service_factory: Callable[[], V2AccountResourceService],
    principal: UserPrincipal,
    unauthenticated_user: str,
    country_id: str,
) -> MeUpgradeResponse | JSONResponse:
    """Move a browser's unauthenticated user into the signed-in account."""

    def upgrade() -> MeUpgradeResponse:
        result = service_factory().upgrade_account(
            principal=principal,
            unauthenticated_user_id=UUID(unauthenticated_user),
            country_id=country_id,
        )
        return MeUpgradeResponse(result=MeUpgradeResult.from_upgrade(result))

    return user_resource_operation(upgrade)


def build_v2_me_router(dependencies: NativeRouteDependencies) -> APIRouter:
    """Build account routes without opening a connection."""
    require_user = dependencies.require_user
    router = APIRouter(
        prefix="/v2",
        responses=USER_RESOURCE_ERROR_RESPONSES,
        dependencies=[Depends(require_user)],
    )
    service_factory = _service_factory(dependencies)
    require_signed_in_user = _signed_in_user_dependency(require_user)

    @router.get(
        "/me",
        response_model=MeDetailResponse,
        summary="Read the current user",
        description=(
            "For a bearer access token, returns the PolicyEngine user, creating "
            "it on the first call with primary_country set from country_id. For "
            "the PolicyEngine-Unauthenticated-User header, returns the "
            "browser's unauthenticated user, or 404 before its first saved "
            "record; reading never creates one."
        ),
    )
    def get_me(
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
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
        description="Unauthenticated users cannot edit account details (403).",
    )
    def patch_me(
        body: AccountPatchRequest,
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
        _size: Annotated[None, Depends(enforce_user_write_request_size)],
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
            },
            503: {
                "model": V2ErrorResponse,
                "description": (
                    "Auth0 Management credentials could not be obtained, or "
                    "persistence is unavailable; nothing was deleted."
                ),
            },
        },
        summary="Delete the current user and all of their saved records",
        description=(
            "For a signed-in user, obtains Auth0 Management credentials first "
            "when they are configured, then deletes the user's legacy user "
            "mappings, the user (identities and associations cascade), and the "
            "Auth0 user. For an unauthenticated user, deletes the user and its "
            "associations and never calls Auth0; 204 even when it does not "
            "exist."
        ),
    )
    def delete_me(
        _query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> Response | JSONResponse:
        def delete() -> Response:
            service_factory().delete_account(principal=principal)
            return Response(status_code=204)

        return user_resource_operation(delete)

    @router.get(
        "/me/export",
        response_model=MeExportResponse,
        summary="Export the current user and every saved record",
        description=(
            "Covers every country, not only country_id. user is null, and every "
            "list empty, for an unauthenticated user with no saved records."
        ),
    )
    def export_me(
        query: CountryQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> MeExportResponse | JSONResponse:
        def export() -> MeExportResponse:
            result = service_factory().export_account(
                principal=principal,
                country_id=query.country_id,
            )
            return MeExportResponse(result=MeExportResult.from_export(result))

        return user_resource_operation(export)

    @router.post(
        "/me/upgrade",
        response_model=MeUpgradeResponse,
        summary="Move this browser's unauthenticated user into the signed-in account",
        description=(
            "Requires both a bearer access token and the "
            "PolicyEngine-Unauthenticated-User header. When the signed-in "
            "identity has no account yet, the unauthenticated user becomes it "
            "in place, keeping its ID and records (converted). When the "
            "identity already has an account, every record moves to that "
            "account with its ID unchanged and the unauthenticated user is "
            "deleted (merged). When the header names no unauthenticated user, "
            "including a signed-in account's ID, nothing moves (none). The "
            "response is the signed-in account."
        ),
    )
    def upgrade_me(
        query: CountryQueryDependency,
        principal: Annotated[UserPrincipal, Depends(require_signed_in_user)],
        unauthenticated_user: Annotated[
            str,
            Header(
                alias=UNAUTHENTICATED_USER_HEADER,
                pattern=CANONICAL_UUID_PATTERN,
                description="The browser's unauthenticated user ID (a canonical UUID).",
            ),
        ],
        _size: Annotated[None, Depends(enforce_user_write_request_size)],
    ) -> MeUpgradeResponse | JSONResponse:
        return _upgrade_account(
            service_factory, principal, unauthenticated_user, query.country_id
        )

    return router
