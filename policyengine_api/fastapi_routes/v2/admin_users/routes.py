"""Native FastAPI routes for admins to find users and change their types.

Every route requires an admin: the router checks the caller's stored type
before any route runs (403 below admin), and each service operation checks it
again inside its own transaction. Unauthenticated users are never listed or
changed, since their IDs are their browsers' credentials.

Users' emails and names come from Auth0 when the Public API has user profile
settings, read for each request and never stored; see AdminUserItem.
"""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse

from policyengine_api.data.v2.models import UserType
from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2UserTypeResourceService,
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
        "description": (
            "The request does not match the schema, or an email search's text "
            "holds < or >, or more than 200 Auth0 users match it."
        ),
    },
    500: {
        "model": V2ErrorResponse,
        "description": "The operation could not be completed.",
    },
    503: {
        "model": V2ErrorResponse,
        "description": (
            "User authentication or persistence is unavailable, or, for an "
            "email search, users' emails can't be read from Auth0."
        ),
    },
}

EMAILS_AND_NAMES_DESCRIPTION = (
    "Each user's email, first_name and last_name are read from Auth0 for "
    "this request and never stored; when Auth0 has none, or can't answer, "
    "the stored values are returned."
)


def _service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2UserTypeResourceService]:
    if dependencies.v2_user_type_service_factory is not None:
        return dependencies.v2_user_type_service_factory
    return _default_v2_user_type_service_factory


def build_v2_admin_user_router(dependencies: NativeRouteDependencies) -> APIRouter:
    """Build admins' user-type routes without opening a connection."""
    require_user = dependencies.require_user
    service_factory = _service_factory(dependencies)
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
            "containing it, ignoring case; every character matches itself. "
            "The search covers stored emails and, with Auth0 user profiles "
            "configured, Auth0 emails: an Auth0 email matches when it "
            "contains the text, or, for fewer than three characters, starts "
            "with it. Auth0's search is eventually consistent, so a "
            "just-changed email may be missing. Text with < or >, which no "
            "email address holds, is refused (422), and so is text that "
            "more than 200 Auth0 users match: enter more of it. When Auth0 "
            "can't answer the search, the response is 503. "
            + EMAILS_AND_NAMES_DESCRIPTION
            + " Unauthenticated users are never listed."
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
        description=(
            "Admins only. An unauthenticated user's ID is not found (404). "
            + EMAILS_AND_NAMES_DESCRIPTION
        ),
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
            "read is not detected. Demoting the last admin is refused (409) too. "
            "The change is committed before the response's email and names are "
            "read; " + EMAILS_AND_NAMES_DESCRIPTION
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

    @router.get(
        "/users/{user_id}/user-type-changes",
        response_model=UserTypeChangeListResponse,
        summary="Read a signed-in user's recorded type changes, newest first",
        description=(
            "Admins only. changed_by_email is the admin's email, read from "
            "Auth0 for this request and never stored; when Auth0 has none, or "
            "can't answer, it is the stored one."
        ),
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
