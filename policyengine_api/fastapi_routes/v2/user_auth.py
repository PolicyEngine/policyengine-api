"""HTTP adapter from bearer access tokens to verified user principals.

User-owned routes attach ``NativeRouteDependencies.require_user`` at router
level, so authentication runs before query and body validation. Failures map
to the shared API v2 error envelope:

- no bearer token, or an invalid token: 401 with ``WWW-Authenticate: Bearer``;
- a machine (``…@clients``) principal: 403;
- authentication not configured, or signing keys unreachable: 503.
"""

from __future__ import annotations

from policyengine_api.fastapi_routes.v2.errors import (
    V2AuthenticationRequiredError,
    V2AuthenticationUnavailableError,
    V2PermissionDeniedError,
)
from policyengine_api.libs.user_auth import (
    InvalidBearerTokenError,
    MissingBearerTokenError,
    PrincipalKind,
    UserAuthConfigurationError,
    UserAuthUnavailableError,
    authenticate_bearer,
    load_user_auth_settings,
)
from policyengine_api.services.v2.identity.types import UserPrincipal


def authenticate_user_request(authorization: str | None) -> UserPrincipal:
    """Return the signed-in user principal or raise a typed HTTP failure."""

    try:
        settings = load_user_auth_settings()
    except UserAuthConfigurationError as error:
        raise V2AuthenticationUnavailableError(
            "User authentication is unavailable"
        ) from error
    try:
        principal = authenticate_bearer(authorization, settings)
    except MissingBearerTokenError as error:
        raise V2AuthenticationRequiredError("Authentication is required") from error
    except InvalidBearerTokenError as error:
        raise V2AuthenticationRequiredError(
            "The bearer access token is invalid",
            invalid_token=True,
        ) from error
    except UserAuthUnavailableError as error:
        raise V2AuthenticationUnavailableError(
            "User authentication is unavailable"
        ) from error
    if principal.kind is PrincipalKind.CLIENT:
        raise V2PermissionDeniedError(
            "This resource requires a signed-in user; machine clients are not permitted"
        )
    return UserPrincipal(
        issuer=principal.issuer,
        subject=principal.subject,
        email=principal.email,
    )
