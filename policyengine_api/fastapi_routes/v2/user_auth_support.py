"""HTTP adapter from request credentials to account principals.

User-owned routes attach ``NativeRouteDependencies.require_user`` at router
level, so authentication runs before query and body validation. A request
authenticates as:

- the signed-in user of an ``Authorization: Bearer`` access token, which
  takes precedence over every other credential;
- otherwise, the unauthenticated user named by a canonical UUID in the
  ``PolicyEngine-Unauthenticated-User`` header, which needs no Auth0
  configuration.

A request from a credentialed server, whose own client-credentials token is in
``Authorization``, authenticates the user it forwards instead: the signed-in
user's token in ``PolicyEngine-User-Authorization: Bearer``, which takes the
place of ``Authorization`` above, or the same unauthenticated-user header.
That user is then authenticated by the same code as a direct request's
credential. A forwarded token is not checked before routing, so an invalid
one gets the ``invalid_token`` challenge below, and a forwarded machine token
gets 403 even from an unlisted client. Without a server credential the
forwarded header is ignored.

Failures map to the shared API v2 error envelope:

- no credential, an invalid token, or a malformed unauthenticated-user
  header: 401 with ``WWW-Authenticate: Bearer``;
- a machine (``…@clients``) principal: 403;
- a bearer token while authentication is not configured, or while signing
  keys are unreachable: 503.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.fastapi_routes.v2.errors_support import (
    V2AuthenticationRequiredError,
    V2AuthenticationUnavailableError,
    V2PermissionDeniedError,
)
from policyengine_api.libs.user_auth import (
    UNAUTHENTICATED_USER_HEADER,
    InvalidBearerTokenError,
    InvalidUnauthenticatedUserError,
    MissingBearerTokenError,
    PrincipalKind,
    UserAuthConfigurationError,
    UserAuthUnavailableError,
    authenticate_bearer,
    load_user_auth_settings,
    unauthenticated_user_id,
)
from policyengine_api.services.v2.identity.types import (
    AccountPrincipal,
    UnauthenticatedPrincipal,
    UserPrincipal,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

REJECTED_BEARER_MESSAGE = "The bearer access token is invalid"


def authenticate_user_request(authorization: str | None) -> UserPrincipal:
    """Return the signed-in user principal or raise a typed HTTP failure."""
    try:
        settings = load_user_auth_settings()
    except UserAuthConfigurationError as error:
        msg = "User authentication is unavailable"
        raise V2AuthenticationUnavailableError(msg) from error
    try:
        principal = authenticate_bearer(authorization, settings)
    except MissingBearerTokenError as error:
        msg = "Authentication is required"
        raise V2AuthenticationRequiredError(msg) from error
    except InvalidBearerTokenError as error:
        msg = REJECTED_BEARER_MESSAGE
        raise V2AuthenticationRequiredError(
            msg,
            invalid_token=True,
        ) from error
    except UserAuthUnavailableError as error:
        msg = "User authentication is unavailable"
        raise V2AuthenticationUnavailableError(msg) from error
    if principal.kind is PrincipalKind.CLIENT:
        msg = (
            "This resource requires a signed-in user; machine clients are not permitted"
        )
        raise V2PermissionDeniedError(msg)
    return UserPrincipal(
        issuer=principal.issuer,
        subject=principal.subject,
        email=principal.email,
    )


def forwarded_user_credential(header_values: Sequence[str]) -> str | None:
    """Return the one forwarded user credential, or None when none is sent.

    A blank value counts as none. Two or more values are refused as an
    invalid token, so no layer can read a different one from the layer that
    checked it.
    """
    if len(header_values) > 1:
        raise V2AuthenticationRequiredError(REJECTED_BEARER_MESSAGE, invalid_token=True)
    if not header_values or not header_values[0].strip():
        return None
    return header_values[0]


def authenticate_account_request(
    authorization: str | None,
    unauthenticated_user: str | None,
) -> AccountPrincipal:
    """Return the request's account principal or raise a typed HTTP failure.

    ``authorization`` is the user's bearer credential: the request's
    ``Authorization`` header, or for a credentialed server the forwarded
    ``PolicyEngine-User-Authorization`` header. It is validated as for any
    signed-in request and the unauthenticated-user header is then ignored.
    Without one, the header selects the browser's unauthenticated user.
    """
    if authorization is None and unauthenticated_user is not None:
        try:
            return UnauthenticatedPrincipal(
                user_id=unauthenticated_user_id(unauthenticated_user)
            )
        except InvalidUnauthenticatedUserError as error:
            msg = f"The {UNAUTHENTICATED_USER_HEADER} header must be a canonical UUID"
            raise V2AuthenticationRequiredError(msg) from error
    return authenticate_user_request(authorization)


def require_signed_in_principal(principal: AccountPrincipal) -> UserPrincipal:
    """Refuse an unauthenticated principal where only a signed-in user may act."""
    if isinstance(principal, UserPrincipal):
        return principal
    msg = "Sign in with a bearer access token"
    raise V2AuthenticationRequiredError(msg)
