"""Inbound authentication for user-owned Public API routes.

The Public API accepts RS256 access tokens issued by the PolicyEngine Auth0
tenant for the Public API resource server. The decoder is ported from the
Simulation Entrypoint (``policyengine_simulation_entry.auth``): the JWKS is
fetched from ``{issuer}.well-known/jwks.json`` and ``iss``/``aud`` are
verified. Machine-to-machine tokens (``…@clients`` subjects) are classified
as client principals so user routes can refuse them.

A signed-out browser instead sends ``PolicyEngine-Unauthenticated-User``: a
random UUID it generates once and keeps. That UUID is a bearer credential for
the browser's unauthenticated user; it needs no Auth0 configuration.

This module never logs a token, subject, email address, or browser UUID.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
import logging
import os
import re
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import UUID

import jwt


PUBLIC_API_AUTH_REQUIRED_ENV = "PUBLIC_API_AUTH_REQUIRED"
PUBLIC_API_AUTH_ISSUER_ENV = "PUBLIC_API_AUTH_ISSUER"
PUBLIC_API_AUTH_AUDIENCE_ENV = "PUBLIC_API_AUTH_AUDIENCE"
PUBLIC_API_AUTH_ENV_VARS = (
    PUBLIC_API_AUTH_REQUIRED_ENV,
    PUBLIC_API_AUTH_ISSUER_ENV,
    PUBLIC_API_AUTH_AUDIENCE_ENV,
)

UNAUTHENTICATED_USER_HEADER = "PolicyEngine-Unauthenticated-User"
# The canonical lowercase, hyphenated form that crypto.randomUUID() produces.
CANONICAL_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

CLIENT_SUBJECT_SUFFIX = "@clients"
CLIENT_CREDENTIALS_GRANT = "client-credentials"
TOKEN_ALGORITHMS = ("RS256",)
REQUIRED_TOKEN_CLAIMS = ("exp", "iss", "aud", "sub")
MAXIMUM_EMAIL_LENGTH = 320
JWKS_TIMEOUT_SECONDS = 5

logger = logging.getLogger(__name__)


class UserAuthConfigurationError(RuntimeError):
    """Raised when the inbound user-authentication settings are unsafe."""


class UserAuthError(Exception):
    """Base class for a request that cannot be authenticated."""


class MissingBearerTokenError(UserAuthError):
    """Raised when a request carries no bearer access token."""


class InvalidBearerTokenError(UserAuthError):
    """Raised when a bearer token fails signature or claim validation."""


class UserAuthUnavailableError(UserAuthError):
    """Raised when authentication cannot be performed by this deployment."""


class InvalidUnauthenticatedUserError(UserAuthError):
    """Raised when the unauthenticated-user header is not a canonical UUID."""


class PrincipalKind(StrEnum):
    USER = "user"
    CLIENT = "client"


@dataclass(frozen=True)
class UserAuthSettings:
    """Validated inbound authentication settings."""

    required: bool
    issuer: str
    audience: str

    @property
    def configured(self) -> bool:
        return bool(self.issuer and self.audience)


@dataclass(frozen=True)
class VerifiedPrincipal:
    """Identity asserted by one validated access token."""

    issuer: str
    subject: str
    kind: PrincipalKind
    email: str | None = None


class TokenDecoder(Protocol):
    def decode(self, token: str) -> Mapping[str, Any]: ...


def _normalized_issuer(value: str) -> str:
    return f"{value.rstrip('/')}/" if value else ""


def _validate_issuer_url(value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise UserAuthConfigurationError(
            f"{PUBLIC_API_AUTH_ISSUER_ENV} must be an absolute HTTPS URL without "
            "credentials, parameters, a query string, or a fragment"
        )


def load_user_auth_settings(
    environ: Mapping[str, str] | None = None,
) -> UserAuthSettings:
    """Load and validate the inbound user-authentication configuration."""

    values = os.environ if environ is None else environ
    required_value = values.get(PUBLIC_API_AUTH_REQUIRED_ENV, "").strip()
    if required_value not in {"", "0", "1"}:
        raise UserAuthConfigurationError(
            f"{PUBLIC_API_AUTH_REQUIRED_ENV} must be 0 or 1"
        )
    required = required_value == "1"
    issuer = _normalized_issuer(values.get(PUBLIC_API_AUTH_ISSUER_ENV, "").strip())
    audience = values.get(PUBLIC_API_AUTH_AUDIENCE_ENV, "").strip()
    if bool(issuer) != bool(audience):
        raise UserAuthConfigurationError(
            f"Set both {PUBLIC_API_AUTH_ISSUER_ENV} and "
            f"{PUBLIC_API_AUTH_AUDIENCE_ENV}, or neither"
        )
    if required and not issuer:
        raise UserAuthConfigurationError(
            f"{PUBLIC_API_AUTH_REQUIRED_ENV}=1 requires "
            f"{PUBLIC_API_AUTH_ISSUER_ENV} and {PUBLIC_API_AUTH_AUDIENCE_ENV}"
        )
    if issuer:
        _validate_issuer_url(issuer)
    return UserAuthSettings(required=required, issuer=issuer, audience=audience)


class JWTDecoder:
    """Validate Auth0 RS256 access tokens without database dependencies."""

    def __init__(
        self,
        issuer: str,
        audience: str,
        *,
        jwks_client: jwt.PyJWKClient | None = None,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.jwks_client = jwks_client or jwt.PyJWKClient(
            f"{issuer}.well-known/jwks.json",
            cache_keys=True,
            timeout=JWKS_TIMEOUT_SECONDS,
        )

    def decode(self, token: str) -> Mapping[str, Any]:
        signing_key = self.jwks_client.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            signing_key,
            algorithms=list(TOKEN_ALGORITHMS),
            audience=self.audience,
            issuer=self.issuer,
            options={"require": list(REQUIRED_TOKEN_CLAIMS)},
        )


@lru_cache(maxsize=8)
def _decoder(issuer: str, audience: str) -> JWTDecoder:
    return JWTDecoder(issuer=issuer, audience=audience)


def reset_decoder_cache() -> None:
    """Clear cached decoders for tests and signing-key or tenant rotations."""

    _decoder.cache_clear()


def bearer_token(authorization: str | None) -> str:
    """Return the credentials of an ``Authorization: Bearer`` header."""

    if not authorization:
        raise MissingBearerTokenError("a bearer access token is required")
    scheme, _, credentials = authorization.strip().partition(" ")
    credentials = credentials.strip()
    if scheme.lower() != "bearer" or not credentials:
        raise MissingBearerTokenError("a bearer access token is required")
    return credentials


def unauthenticated_user_id(value: str) -> UUID:
    """Return the browser UUID carried by the unauthenticated-user header."""

    if re.fullmatch(CANONICAL_UUID_PATTERN, value) is None:
        raise InvalidUnauthenticatedUserError(
            f"{UNAUTHENTICATED_USER_HEADER} must be a canonical UUID"
        )
    return UUID(value)


def _verified_email(claims: Mapping[str, Any]) -> str | None:
    email = claims.get("email")
    if claims.get("email_verified") is not True or not isinstance(email, str):
        return None
    email = email.strip()
    if not email or len(email) > MAXIMUM_EMAIL_LENGTH:
        return None
    return email


def classify_principal(claims: Mapping[str, Any]) -> VerifiedPrincipal:
    """Build a principal from already-validated token claims."""

    subject = claims.get("sub")
    issuer = claims.get("iss")
    if not isinstance(subject, str) or not subject.strip():
        raise InvalidBearerTokenError("the access token has no subject")
    if not isinstance(issuer, str) or not issuer:
        raise InvalidBearerTokenError("the access token has no issuer")
    is_client = (
        subject.endswith(CLIENT_SUBJECT_SUFFIX)
        or claims.get("gty") == CLIENT_CREDENTIALS_GRANT
    )
    return VerifiedPrincipal(
        issuer=issuer,
        subject=subject,
        kind=PrincipalKind.CLIENT if is_client else PrincipalKind.USER,
        email=None if is_client else _verified_email(claims),
    )


def authenticate_bearer(
    authorization: str | None,
    settings: UserAuthSettings,
    *,
    decoder: TokenDecoder | None = None,
) -> VerifiedPrincipal:
    """Validate one Authorization header and classify its principal."""

    token = bearer_token(authorization)
    if not settings.configured:
        raise UserAuthUnavailableError("user authentication is not configured")
    selected_decoder = decoder or _decoder(settings.issuer, settings.audience)
    try:
        claims = selected_decoder.decode(token)
    except jwt.PyJWKClientConnectionError as error:
        logger.warning(
            "public_api_user_auth_unavailable",
            extra={"policyengine_attributes": {"error_type": type(error).__name__}},
        )
        raise UserAuthUnavailableError(
            "the signing keys could not be retrieved"
        ) from error
    except (jwt.PyJWTError, ValueError) as error:
        logger.info(
            "public_api_user_auth_rejected",
            extra={"policyengine_attributes": {"error_type": type(error).__name__}},
        )
        raise InvalidBearerTokenError("the bearer access token is invalid") from error
    if claims.get("iss") != settings.issuer:
        raise InvalidBearerTokenError("the bearer access token is invalid")
    return classify_principal(claims)
