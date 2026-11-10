"""Native FastAPI routes for admins to find users, change their types and delete them.

Every route requires an admin: the router checks the caller's stored type
before any route runs (403 below admin), and each service operation checks it
again inside its own transaction. Unauthenticated users are never listed,
changed or deleted, since their IDs are their browsers' credentials.
"""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse, Response

from policyengine_api.data.v2.models import UserType
from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2AccountResourceService,
    V2UserTypeResourceService,
    _default_v2_account_service_factory,
    _default_v2_user_type_service_factory,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.admin_users.request_models import (
    UserTypePatchRequest,
)
from policyengine_api.fastapi_routes.v2.admin_users.response_models import (
    AdminUserItem,
    AdminUserPageResponse,
    AdminUserPageResult,
    AdminUserResponse,
    AdminUserResult,
    UserTypeChangeItem,
    UserTypeChangeListResponse,
    UserTypeChangeListResult,
)
from policyengine_api.fastapi_routes.v2.errors_support import V2ErrorResponse
from policyengine_api.fastapi_routes.v2.user_auth_support import (
    require_signed_in_principal,
)
from policyengine_api.fastapi_routes.v2.user_resources_support import (
    enforce_user_write_request_size,
    user_resource_operation,
)
from policyengine_api.fastapi_routes.v2.user_type_support import (
    minimum_user_type_dependency,
)
from policyengine_api.query_parameters import AdminUserCollectionQuery
from policyengine_api.services.v2.identity.types import AccountPrincipal
from policyengine_api.services.v2.user_types.types import AdminUserSearch

AdminUserCollectionQueryDependency = Annotated[
    AdminUserCollectionQuery, Depends(query_dependency(AdminUserCollectionQuery))
]

ADMIN_USER_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {
        "model": V2ErrorResponse,
        "description": (
            "A valid bearer access token is required. The response carries "
            "WWW-Authenticate: Bearer."
        ),
    },
    403: {
        "model": V2ErrorResponse,
        "description": "Only admins may use these routes.",
    },
    404: {
        "model": V2ErrorResponse,
        "description": "No signed-in user has this ID.",
    },
    409: {
        "model": V2ErrorResponse,
        "description": (
            "The user's type is no longer the expected one, or the change would "
            "leave no admin."
        ),
    },
    413: {
        "model": V2ErrorResponse,
        "description": "The request body exceeds 256 KiB.",
    },
    422: {
        "model": V2ErrorResponse,
        "description": "The request does not match the schema.",
    },
    500: {
        "model": V2ErrorResponse,
        "description": "The operation could not be completed.",
    },
    503: {
        "model": V2ErrorResponse,
        "description": "User authentication or persistence is unavailable.",
    },
}


ADMIN_ACCOUNT_DELETION_RESPONSES: dict[int | str, dict[str, Any]] = {
    409: {
        "model": V2ErrorResponse,
        "description": (
            "The user is the only admin, which happens only when admins delete "
            "their own account; make another user an admin first. Nothing was "
            "deleted."
        ),
    },
    502: {
        "model": V2ErrorResponse,
        "description": (
            "The account's data was deleted, but some Auth0 users of its "
            "sign-in identities could not be removed; every one was tried. "
            "The message says how many remain. A retry answers 404, since the "
            "user is gone: find the remaining Auth0 users in Auth0 by the "
            "person's email and delete them there."
        ),
    },
    503: {
        "model": V2ErrorResponse,
        "description": (
            "Auth0 Management credentials could not be obtained, or "
            "persistence is unavailable; nothing was deleted."
        ),
    },
}


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2UserTypeResourceService]:
    if dependencies.v2_user_type_service_factory is not None:
        return dependencies.v2_user_type_service_factory
    return _default_v2_user_type_service_factory


def _account_service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2AccountResourceService]:
    if dependencies.v2_account_service_factory is not None:
        return dependencies.v2_account_service_factory
    return _default_v2_account_service_factory


def _delete_user_account(
    account_service_factory: Callable[[], V2AccountResourceService],
    principal: AccountPrincipal,
    user_id: UUID,
) -> Response | JSONResponse:
    """Delete a signed-in user's account for the admin ``principal``."""
    # The router admitted only an admin, and admins are signed in.
    signed_in = require_signed_in_principal(principal)

    def delete() -> Response:
        account_service_factory().delete_user_account_as_admin(
            principal=signed_in, user_id=user_id
        )
        return Response(status_code=204)

    return user_resource_operation(delete)


def build_v2_admin_user_router(dependencies: NativeRouteDependencies) -> APIRouter:
    """Build admins' user routes without opening a connection."""
    require_user = dependencies.require_user
    service_factory = _service_factory(dependencies)
    account_service_factory = _account_service_factory(dependencies)
    require_admin = minimum_user_type_dependency(
        require_user, service_factory, UserType.ADMIN
    )
    router = APIRouter(
        prefix="/v2/admin",
        responses=ADMIN_USER_ERROR_RESPONSES,
        dependencies=[Depends(require_user), Depends(require_admin)],
    )

    @router.get(
        "/users",
        response_model=AdminUserPageResponse,
        summary="List signed-in users, newest first",
        description=(
            "Admins only. With email, lists only users with an email address "
            "containing it, ignoring case; % and _ match themselves. "
            "Unauthenticated users are never listed."
        ),
    )
    def list_users(
        query: AdminUserCollectionQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> AdminUserPageResponse | JSONResponse:
        def read() -> AdminUserPageResponse:
            page = service_factory().list_users(
                principal=principal,
                search=AdminUserSearch(
                    email=query.email, offset=query.offset, limit=query.limit
                ),
            )
            return AdminUserPageResponse(result=AdminUserPageResult.from_page(page))

        return user_resource_operation(read)

    @router.get(
        "/users/{user_id}",
        response_model=AdminUserResponse,
        summary="Read one signed-in user",
        description="Admins only. An unauthenticated user's ID is not found (404).",
    )
    def get_user(
        user_id: UUID,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> AdminUserResponse | JSONResponse:
        def read() -> AdminUserResponse:
            user = service_factory().get_user(principal=principal, user_id=user_id)
            return AdminUserResponse(
                result=AdminUserResult(item=AdminUserItem.from_read(user))
            )

        return user_resource_operation(read)

    @router.patch(
        "/users/{user_id}",
        response_model=AdminUserResponse,
        summary="Change a signed-in user's type",
        description=(
            "Admins only. Records the change in the user's type history. Setting "
            "the type the user already has changes and records nothing, whatever "
            "expected_user_type is. Otherwise expected_user_type, the user's type "
            "as the admin last read it, must still be the stored type: when it "
            "differs, the change is refused (409) and nothing is written. Only "
            "the type is compared, so a type changed and changed back since the "
            "read is not detected. Demoting the last admin is refused (409) too."
        ),
    )
    def change_user_type(
        user_id: UUID,
        body: UserTypePatchRequest,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
        _size: Annotated[None, Depends(enforce_user_write_request_size)],
    ) -> AdminUserResponse | JSONResponse:
        def change() -> AdminUserResponse:
            user = service_factory().change_user_type(
                principal=principal,
                user_id=user_id,
                user_type=UserType(body.user_type),
                expected_user_type=UserType(body.expected_user_type),
            )
            return AdminUserResponse(
                result=AdminUserResult(item=AdminUserItem.from_read(user))
            )

        return user_resource_operation(change)

    @router.delete(
        "/users/{user_id}",
        response_model=None,
        status_code=204,
        response_class=Response,
        responses=ADMIN_ACCOUNT_DELETION_RESPONSES,
        summary="Delete a signed-in user's account and all of their saved records",
        description=(
            "Admins only. Deletes the user exactly as DELETE /v2/me deletes "
            "the caller's own account: obtains Auth0 Management credentials "
            "first when they are configured, then deletes the user's legacy "
            "user mappings, the user (identities and saved records cascade), "
            "and the Auth0 users of the user's sign-in identities. An "
            "unauthenticated user's ID is not found (404). Admins may delete "
            "their own account here too: as with DELETE /v2/me, the only "
            "admin's deletion is refused (409); otherwise the account is "
            "deleted and the admin's next request has no user, so the admin "
            "routes answer 403. Each deletion is recorded with the admin's and "
            "the deleted user's IDs."
        ),
    )
    def delete_user(
        user_id: UUID,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> Response | JSONResponse:
        return _delete_user_account(account_service_factory, principal, user_id)

    @router.get(
        "/users/{user_id}/user-type-changes",
        response_model=UserTypeChangeListResponse,
        summary="Read a signed-in user's recorded type changes, newest first",
        description="Admins only.",
    )
    def list_user_type_changes(
        user_id: UUID,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> UserTypeChangeListResponse | JSONResponse:
        def read() -> UserTypeChangeListResponse:
            changes = service_factory().list_user_type_changes(
                principal=principal, user_id=user_id
            )
            return UserTypeChangeListResponse(
                result=UserTypeChangeListResult(
                    items=[UserTypeChangeItem.from_read(change) for change in changes]
                )
            )

        return user_resource_operation(read)

    return router
