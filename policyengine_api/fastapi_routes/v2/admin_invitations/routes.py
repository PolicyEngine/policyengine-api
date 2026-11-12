"""Native FastAPI routes for admins' email invitations.

Every route requires an admin: the router checks the caller's stored type
before any route runs (403 below admin), and each service operation checks it
again inside its own transaction. An invitation's email is sent after the
invitation commits, through Postmark; a failed send leaves it open with the
failure in ``last_send_error``, so the admin can resend it.
"""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse, Response

from policyengine_api.data.v2.models import UserType
from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2UserInvitationResourceService,
    V2UserTypeResourceService,
    _default_v2_user_invitation_service_factory,
    _default_v2_user_type_service_factory,
)
from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.fastapi_routes.v2.admin_invitations.request_models import (
    InvitationCreateRequest,
)
from policyengine_api.fastapi_routes.v2.admin_invitations.response_models import (
    AdminInvitationItem,
    AdminInvitationPageResponse,
    AdminInvitationPageResult,
    AdminInvitationResponse,
    AdminInvitationResult,
)
from policyengine_api.fastapi_routes.v2.errors_support import V2ErrorResponse
from policyengine_api.fastapi_routes.v2.user_resources_support import (
    enforce_user_write_request_size,
    user_resource_operation,
)
from policyengine_api.fastapi_routes.v2.user_type_support import (
    minimum_user_type_dependency,
)
from policyengine_api.query_parameters import AdminInvitationCollectionQuery
from policyengine_api.services.v2.identity.types import AccountPrincipal
from policyengine_api.services.v2.user_invitations.types import AdminInvitationSearch

AdminInvitationCollectionQueryDependency = Annotated[
    AdminInvitationCollectionQuery,
    Depends(query_dependency(AdminInvitationCollectionQuery)),
]

ADMIN_INVITATION_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
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
NOT_OPEN_RESPONSE: dict[int | str, dict[str, Any]] = {
    404: {
        "model": V2ErrorResponse,
        "description": (
            "No open invitation has this ID: it is unknown, accepted or revoked."
        ),
    },
}
SEND_DESCRIPTION = (
    "The email is sent through Postmark after the invitation commits, and "
    "retried a few times; when every attempt fails, or Postmark isn't "
    "configured, the invitation stays open with last_sent_at null and "
    "last_send_error naming why. The link is valid for 7 days."
)


def _invitation_service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2UserInvitationResourceService]:
    if dependencies.v2_user_invitation_service_factory is not None:
        return dependencies.v2_user_invitation_service_factory
    return _default_v2_user_invitation_service_factory


def _user_type_service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2UserTypeResourceService]:
    if dependencies.v2_user_type_service_factory is not None:
        return dependencies.v2_user_type_service_factory
    return _default_v2_user_type_service_factory


def build_v2_admin_invitation_router(
    dependencies: NativeRouteDependencies,
) -> APIRouter:
    """Build admins' invitation routes without opening a connection."""
    require_user = dependencies.require_user
    service_factory = _invitation_service_factory(dependencies)
    require_admin = minimum_user_type_dependency(
        require_user, _user_type_service_factory(dependencies), UserType.ADMIN
    )
    router = APIRouter(
        prefix="/v2/admin",
        responses=ADMIN_INVITATION_ERROR_RESPONSES,
        dependencies=[Depends(require_user), Depends(require_admin)],
    )

    @router.post(
        "/invitations",
        response_model=AdminInvitationResponse,
        status_code=201,
        summary="Invite an email address to become an author or admin",
        description=(
            "Admins only. Creates the invitation and emails its link to the "
            "address; an open invitation to the same address, compared "
            "ignoring case, is revoked first, so its link stops working. "
            + SEND_DESCRIPTION
            + " The response is 201 even when the send failed."
        ),
    )
    def create_invitation(
        body: InvitationCreateRequest,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
        _size: Annotated[None, Depends(enforce_user_write_request_size)],
    ) -> AdminInvitationResponse | JSONResponse:
        def create() -> AdminInvitationResponse:
            invitation = service_factory().create_invitation(
                principal=principal,
                email=body.email,
                user_type=UserType(body.user_type),
            )
            return AdminInvitationResponse(
                result=AdminInvitationResult(
                    item=AdminInvitationItem.from_read(invitation)
                )
            )

        return user_resource_operation(create)

    @router.get(
        "/invitations",
        response_model=AdminInvitationPageResponse,
        summary="List open invitations, newest first",
        description=(
            "Admins only. Lists the invitations that are neither accepted nor "
            "revoked, expired ones included (expired is true)."
        ),
    )
    def list_invitations(
        query: AdminInvitationCollectionQueryDependency,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> AdminInvitationPageResponse | JSONResponse:
        def read() -> AdminInvitationPageResponse:
            page = service_factory().list_invitations(
                principal=principal,
                search=AdminInvitationSearch(offset=query.offset, limit=query.limit),
            )
            return AdminInvitationPageResponse(
                result=AdminInvitationPageResult.from_page(page)
            )

        return user_resource_operation(read)

    @router.post(
        "/invitations/{invitation_id}/resend",
        response_model=AdminInvitationResponse,
        responses=NOT_OPEN_RESPONSE,
        summary="Email an open invitation again with a new link",
        description=(
            "Admins only. Gives the invitation a new link, so the earlier one "
            "stops working, and a new 7-day expiry, makes the caller its "
            "inviting admin, and emails it again. An expired invitation can be "
            "resent. " + SEND_DESCRIPTION
        ),
    )
    def resend_invitation(
        invitation_id: UUID,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> AdminInvitationResponse | JSONResponse:
        def resend() -> AdminInvitationResponse:
            invitation = service_factory().resend_invitation(
                principal=principal, invitation_id=invitation_id
            )
            return AdminInvitationResponse(
                result=AdminInvitationResult(
                    item=AdminInvitationItem.from_read(invitation)
                )
            )

        return user_resource_operation(resend)

    @router.delete(
        "/invitations/{invitation_id}",
        response_model=None,
        status_code=204,
        response_class=Response,
        responses=NOT_OPEN_RESPONSE,
        summary="Revoke an open invitation",
        description="Admins only. The invitation's link stops working.",
    )
    def revoke_invitation(
        invitation_id: UUID,
        principal: Annotated[AccountPrincipal, Depends(require_user)],
    ) -> Response | JSONResponse:
        def revoke() -> Response:
            service_factory().revoke_invitation(
                principal=principal, invitation_id=invitation_id
            )
            return Response(status_code=204)

        return user_resource_operation(revoke)

    return router
