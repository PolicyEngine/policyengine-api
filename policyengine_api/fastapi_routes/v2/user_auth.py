"""HTTP adapter from request credentials to account principals.

User-owned routes attach ``NativeRouteDependencies.require_user`` at router
level, so authentication runs before query and body validation. A request
authenticates as:

- the signed-in user of an ``Authorization: Bearer`` access token, which
  takes precedence over every other credential;
- otherwise, the unauthenticated user named by a canonical UUID in the
  ``PolicyEngine-Unauthenticated-User`` header, which needs no Auth0
  configuration.

Failures map to the shared API v2 error envelope:

- no credential, an invalid token, or a malformed unauthenticated-user
  header: 401 with ``WWW-Authenticate: Bearer``;
- a machine (``…@clients``) principal: 403;
- a bearer token while authentication is not configured, or while signing
  keys are unreachable: 503.
"""

from __future__ import annotations

from policyengine_api.fastapi_routes.v2.errors import (
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
        msg = "The bearer access token is invalid"
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


def authenticate_account_request(
    authorization: str | None,
    unauthenticated_user: str | None,
) -> AccountPrincipal:
    """Return the request's account principal or raise a typed HTTP failure.

    A bearer token is validated as for any signed-in request and the
    unauthenticated-user header is then ignored. Without one, the header
    selects the browser's unauthenticated user.
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
