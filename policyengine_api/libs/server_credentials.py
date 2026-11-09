"""Server credentials: Auth0 client-credentials tokens from allowed clients.

PolicyEngine's own servers call the Public API with an Auth0
client-credentials access token in ``Authorization: Bearer``. Their clients
live in the Public API's own Auth0 tenant for the environment (decision
1.1 · 5), apart from the tenant that signs users in:

- a server token's issuer is ``PUBLIC_API_SERVER_AUTH_ISSUER`` (for example
  ``https://policyengine-api.uk.auth0.com/``), and its audience is
  ``PUBLIC_API_AUTH_AUDIENCE``, the same Auth0 API identifier users' tokens
  carry;
- a signed-in user's token keeps its issuer, ``PUBLIC_API_AUTH_ISSUER``.

The two issuers must differ. Each token is verified by
:func:`policyengine_api.libs.user_auth.authenticate_bearer` with the settings
of the issuer it names: that tenant's signing keys, issuer and audience. From
the server issuer only a ``<client ID>@clients`` subject is accepted, and the
client ID must be listed in ``PUBLIC_API_SERVER_CLIENT_IDS``: client IDs
separated by commas, with no spaces. An empty or unset list allows no client,
and a list needs the server issuer.

:func:`identify_caller` classifies one request's ``Authorization`` header:

- absent, or only spaces and tabs: no credential (:attr:`CallerKind.NONE`);
- a valid token of a listed client from the server issuer: a server
  (:attr:`CallerKind.SERVER`), with its client ID;
- a valid token of a signed-in user from the users' issuer: a user
  (:attr:`CallerKind.USER`). It is not a server credential; the user routes
  check it again themselves;
- anything else is refused with :class:`CredentialRefusedError`: another
  scheme, a token that fails signature or claim validation (an expired user
  token included), a valid token of an unlisted client, a client token from
  the users' issuer, or a token without a client subject from the server
  issuer.

A bearer token that cannot be checked, because the signing keys cannot be
fetched or the issuer and audience are not set, raises
:class:`CredentialCheckUnavailableError`. Malformed settings raise
:class:`UserAuthConfigurationError` from the loaders, before classification.

This module never logs or returns a token or a user's subject. A client ID is
returned only from a token whose signature and claims are valid.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import jwt

from policyengine_api.libs.user_auth import (
    CLIENT_SUBJECT_SUFFIX,
    PUBLIC_API_AUTH_AUDIENCE_ENV,
    PUBLIC_API_AUTH_ISSUER_ENV,
    InvalidBearerTokenError,
    MissingBearerTokenError,
    PrincipalKind,
    UserAuthConfigurationError,
    UserAuthSettings,
    UserAuthUnavailableError,
    VerifiedPrincipal,
    authenticate_bearer,
    bearer_token,
    load_user_auth_settings,
    validate_issuer_url,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

PUBLIC_API_SERVER_CLIENT_IDS_ENV = "PUBLIC_API_SERVER_CLIENT_IDS"
PUBLIC_API_SERVER_AUTH_ISSUER_ENV = "PUBLIC_API_SERVER_AUTH_ISSUER"
# Only HTTP whitespace (space and tab) makes an Authorization header blank.
HTTP_WHITESPACE = " \t"
# Auth0 client IDs are letters and digits; hyphens and underscores are
# accepted so that test and future identifiers fit too.
CLIENT_ID_PATTERN = r"[A-Za-z0-9_-]+"


class CallerKind(StrEnum):
    """Who a request is from, as its ``Authorization`` header shows."""

    NONE = "none"
    SERVER = "server"
    USER = "user"


class RefusalReason(StrEnum):
    """Why a credential was refused, as it is logged."""

    FAILED_VALIDATION = "invalid_token"
    CLIENT_NOT_ALLOWED = "client_not_allowed"
    DUPLICATE_HEADER = "duplicate_authorization_header"
    CLIENT_FROM_USER_ISSUER = "client_from_user_issuer"
    NON_CLIENT_FROM_SERVER_ISSUER = "non_client_from_server_issuer"


@dataclass(frozen=True)
class RequestCaller:
    """The caller of one request; ``client_id`` is set only for a server."""

    kind: CallerKind
    client_id: str | None = None


NO_CREDENTIAL = RequestCaller(kind=CallerKind.NONE)
SIGNED_IN_USER = RequestCaller(kind=CallerKind.USER)


@dataclass(frozen=True)
class ServerCredentialSettings:
    """Where server tokens come from, and which clients' tokens are accepted.

    ``issuer`` is the Public API's own tenant, normalized to a trailing ``/``,
    or empty when no server token can be accepted.
    """

    allowed_client_ids: frozenset[str]
    issuer: str = ""


class CredentialRefusedError(Exception):
    """Raised for an ``Authorization`` header that is not a valid credential."""

    def __init__(self, reason: RefusalReason, *, client_id: str | None = None) -> None:
        """Record the reason, and the client ID of a valid but unlisted client."""
        super().__init__(reason.value)
        self.reason = reason
        self.client_id = client_id


class CredentialCheckUnavailableError(Exception):
    """Raised when a bearer token cannot be checked by this deployment."""


def load_server_credential_settings(
    environ: Mapping[str, str] | None = None,
) -> ServerCredentialSettings:
    """Load and validate the server issuer and the allow list of client IDs.

    Raise :class:`UserAuthConfigurationError` for a malformed list, a list
    without the server issuer, or a server issuer that is not an HTTPS URL,
    has no audience to check, or equals the users' issuer.
    """
    values = os.environ if environ is None else environ
    issuer = _load_server_issuer(values)
    allow_list = values.get(PUBLIC_API_SERVER_CLIENT_IDS_ENV, "")
    if not allow_list.strip():
        return ServerCredentialSettings(allowed_client_ids=frozenset(), issuer=issuer)
    client_ids = allow_list.split(",")
    if not all(re.fullmatch(CLIENT_ID_PATTERN, client_id) for client_id in client_ids):
        msg = (
            f"{PUBLIC_API_SERVER_CLIENT_IDS_ENV} must be Auth0 client IDs "
            "separated by commas, with no spaces or empty entries"
        )
        raise UserAuthConfigurationError(msg)
    if not issuer:
        msg = (
            f"{PUBLIC_API_SERVER_CLIENT_IDS_ENV} requires "
            f"{PUBLIC_API_SERVER_AUTH_ISSUER_ENV} and {PUBLIC_API_AUTH_AUDIENCE_ENV}"
        )
        raise UserAuthConfigurationError(msg)
    return ServerCredentialSettings(
        allowed_client_ids=frozenset(client_ids), issuer=issuer
    )


def _load_server_issuer(values: Mapping[str, str]) -> str:
    """Return the normalized server issuer, or empty when it is not set."""
    configured_issuer = values.get(PUBLIC_API_SERVER_AUTH_ISSUER_ENV, "").strip()
    if not configured_issuer:
        return ""
    issuer = f"{configured_issuer.rstrip('/')}/"
    validate_issuer_url(issuer, PUBLIC_API_SERVER_AUTH_ISSUER_ENV)
    user_settings = load_user_auth_settings(values)
    if not user_settings.audience:
        msg = (
            f"{PUBLIC_API_SERVER_AUTH_ISSUER_ENV} requires "
            f"{PUBLIC_API_AUTH_AUDIENCE_ENV}"
        )
        raise UserAuthConfigurationError(msg)
    if issuer == user_settings.issuer:
        # From the server issuer only client tokens are accepted, so sharing it
        # with users would refuse every signed-in user.
        msg = (
            f"{PUBLIC_API_SERVER_AUTH_ISSUER_ENV} must differ from "
            f"{PUBLIC_API_AUTH_ISSUER_ENV}"
        )
        raise UserAuthConfigurationError(msg)
    return issuer


def _client_id(subject: str) -> str | None:
    """Return the client ID of a ``<client ID>@clients`` subject, or None."""
    if not subject.endswith(CLIENT_SUBJECT_SUFFIX):
        return None
    client_id = subject.removesuffix(CLIENT_SUBJECT_SUFFIX)
    return client_id if re.fullmatch(CLIENT_ID_PATTERN, client_id) else None


def _claimed_issuer(token: str) -> str | None:
    """Return the issuer a token names, without verifying anything.

    It only chooses which tenant's settings verify the token; the issuer claim
    is then checked against them, with the signature.
    """
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return None
    issuer = claims.get("iss")
    return issuer if isinstance(issuer, str) else None


def _verified_principal(
    authorization: str, settings: UserAuthSettings
) -> VerifiedPrincipal:
    """Verify ``authorization`` against one tenant's settings, or refuse it."""
    try:
        return authenticate_bearer(authorization, settings)
    except (MissingBearerTokenError, InvalidBearerTokenError) as error:
        raise CredentialRefusedError(RefusalReason.FAILED_VALIDATION) from error
    except UserAuthUnavailableError as error:
        msg = "the bearer token cannot be checked"
        raise CredentialCheckUnavailableError(msg) from error


def _server_caller(
    authorization: str,
    auth_settings: UserAuthSettings,
    credential_settings: ServerCredentialSettings,
) -> RequestCaller:
    """Verify a token that names the server issuer as a listed client's."""
    server_settings = UserAuthSettings(
        required=False,
        issuer=credential_settings.issuer,
        audience=auth_settings.audience,
    )
    principal = _verified_principal(authorization, server_settings)
    client_id = (
        _client_id(principal.subject)
        if principal.kind is PrincipalKind.CLIENT
        else None
    )
    if client_id is None:
        raise CredentialRefusedError(RefusalReason.NON_CLIENT_FROM_SERVER_ISSUER)
    if client_id not in credential_settings.allowed_client_ids:
        raise CredentialRefusedError(
            RefusalReason.CLIENT_NOT_ALLOWED, client_id=client_id
        )
    return RequestCaller(kind=CallerKind.SERVER, client_id=client_id)


def identify_caller(
    authorization: str | None,
    auth_settings: UserAuthSettings,
    credential_settings: ServerCredentialSettings,
) -> RequestCaller:
    """Classify one ``Authorization`` header, or refuse it.

    A token that names the server issuer is verified with the server tenant's
    settings and must be a listed client's; any other token is verified with
    the users' settings and must be a user's. Raise
    :class:`CredentialRefusedError` for a header that is not a valid
    credential, and :class:`CredentialCheckUnavailableError` for a bearer token
    that cannot be checked.
    """
    if authorization is None or not authorization.strip(HTTP_WHITESPACE):
        return NO_CREDENTIAL
    try:
        token = bearer_token(authorization)
    except MissingBearerTokenError as error:
        raise CredentialRefusedError(RefusalReason.FAILED_VALIDATION) from error
    if (
        credential_settings.issuer
        and _claimed_issuer(token) == credential_settings.issuer
    ):
        return _server_caller(authorization, auth_settings, credential_settings)
    principal = _verified_principal(authorization, auth_settings)
    if principal.kind is PrincipalKind.USER:
        return SIGNED_IN_USER
    # Server clients live in the Public API's own tenant, not the users'.
    raise CredentialRefusedError(
        RefusalReason.CLIENT_FROM_USER_ISSUER,
        client_id=_client_id(principal.subject),
    )
