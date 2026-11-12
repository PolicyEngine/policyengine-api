"""Native FastAPI routes for the signed-in user's type, under /v2/me.

A signed-in user accepts an admin's email invitation with the token from its
link, and dismisses the notice of their latest type change, which
``GET /v2/me`` reports until then. Both need a bearer access token: the
unauthenticated-user header alone is refused with 401.
"""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from starlette.responses import JSONResponse, Response

from policyengine_api.fastapi_routes.dependencies import (
    NativeRouteDependencies,
    V2UserInvitationResourceService,
    _default_v2_user_invitation_service_factory,
)
from policyengine_api.fastapi_routes.v2.errors_support import (
    V2CodedErrorResponse,
    V2ErrorResponse,
)
from policyengine_api.fastapi_routes.v2.me.account_support import (
    CountryQueryDependency,
    account_service_factory,
    signed_in_user_dependency,
)
from policyengine_api.fastapi_routes.v2.me.request_models import (
    InvitationAcceptRequest,
)
from policyengine_api.fastapi_routes.v2.me.response_models import (
    InvitationAcceptanceItem,
    InvitationAcceptanceResponse,
    InvitationAcceptanceResult,
)
from policyengine_api.fastapi_routes.v2.user_resources_support import (
    USER_RESOURCE_ERROR_RESPONSES,
    enforce_user_write_request_size,
    user_resource_operation,
)
from policyengine_api.services.v2.identity.types import UserPrincipal


def _invitation_service_factory(
    dependencies: NativeRouteDependencies,
) -> Callable[[], V2UserInvitationResourceService]:
    if dependencies.v2_user_invitation_service_factory is not None:
        return dependencies.v2_user_invitation_service_factory
    return _default_v2_user_invitation_service_factory


ACCEPTANCE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {
        "model": V2ErrorResponse,
        "description": (
            "A valid bearer access token is required; the unauthenticated-user "
            "header alone can't accept an invitation."
        ),
    },
    403: {
        # A machine (client-credentials) principal's refusal has no code.
        "model": V2CodedErrorResponse | V2ErrorResponse,
        "description": (
            "code email_mismatch: the signed-in user's verified email isn't the "
            "invited address, compared whole and ignoring case. The invitation "
            "stays open. A machine (client-credentials) principal is also "
            "refused with 403, without a code."
        ),
    },
    409: {
        # A conflict with stored state answers without a code.
        "model": V2CodedErrorResponse | V2ErrorResponse,
        "description": (
            "code inviter_not_admin: the admin who sent the invitation is no "
            "longer an admin. code email_not_verified: Auth0 has no verified "
            "email for the signed-in user yet; try again once it is verified. "
            "A conflict with stored state is also 409, without a code."
        ),
    },
    410: {
        "model": V2CodedErrorResponse,
        "description": (
            "The token can't be accepted. code invitation_not_found: no "
            "invitation has it, including a link replaced by a resend; "
            "invitation_revoked: it was revoked or replaced by a newer "
            "invitation; invitation_expired; invitation_accepted."
        ),
    },
    503: {
        # Unavailable persistence answers without a code.
        "model": V2CodedErrorResponse | V2ErrorResponse,
        "description": (
            "code auth0_unavailable: the signed-in user's email couldn't be "
            "read from Auth0; try again shortly. Persistence being unavailable "
            "is also 503, without a code."
        ),
    },
}


def build_v2_me_user_type_router(dependencies: NativeRouteDependencies) -> APIRouter:
    """Build the invitation acceptance and type-change dismissal routes."""
    require_user = dependencies.require_user
    router = APIRouter(
        prefix="/v2",
        responses=USER_RESOURCE_ERROR_RESPONSES,
        dependencies=[Depends(require_user)],
    )
    service_factory = account_service_factory(dependencies)
    invitation_service_factory = _invitation_service_factory(dependencies)
    require_signed_in_user = signed_in_user_dependency(require_user)

    @router.post(
        "/me/invitations/accept",
        response_model=InvitationAcceptanceResponse,
        responses=ACCEPTANCE_ERROR_RESPONSES,
        summary="Accept an admin's email invitation with its token",
        description=(
            "Signed-in users only. A user with no account yet gets one, with "
            "primary_country from country_id. The signed-in user's email is "
            "read from Auth0 first and never stored; then the token, the "
            "inviting admin, the email's verification and its match with the "
            "invited address are checked, in that order, and each refusal "
            "names its code. On success the user gets the invited type, unless "
            "they already have it or a higher one, the invitation is marked "
            "accepted, and a type change is recorded and emailed to the user."
        ),
    )
    def accept_invitation(
        body: InvitationAcceptRequest,
        query: CountryQueryDependency,
        principal: Annotated[UserPrincipal, Depends(require_signed_in_user)],
        _size: Annotated[None, Depends(enforce_user_write_request_size)],
    ) -> InvitationAcceptanceResponse | JSONResponse:
        def accept() -> InvitationAcceptanceResponse:
            acceptance = invitation_service_factory().accept_invitation(
                principal=principal, token=body.token, country_id=query.country_id
            )
            return InvitationAcceptanceResponse(
                result=InvitationAcceptanceResult(
                    item=InvitationAcceptanceItem.from_acceptance(acceptance)
                )
            )

        return user_resource_operation(accept)

    @router.post(
        "/me/type-changes/{type_change_id}/dismiss",
        response_model=None,
        status_code=204,
        response_class=Response,
        responses={
            404: {
                "model": V2ErrorResponse,
                "description": "The signed-in user has no type change with this ID.",
            },
        },
        summary="Dismiss the notice of a type change",
        description=(
            "Signed-in users only. GET /v2/me then stops reporting the change "
            "as latest_type_change. Dismissing it again changes nothing."
        ),
    )
    def dismiss_type_change(
        type_change_id: UUID,
        _query: CountryQueryDependency,
        principal: Annotated[UserPrincipal, Depends(require_signed_in_user)],
    ) -> Response | JSONResponse:
        def dismiss() -> Response:
            service_factory().dismiss_type_change(
                principal=principal, type_change_id=type_change_id
            )
            return Response(status_code=204)

        return user_resource_operation(dismiss)

    return router
