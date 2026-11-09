"""Server credentials: Auth0 client-credentials tokens from allowed clients.

PolicyEngine's own servers call the Public API with an Auth0
client-credentials access token in ``Authorization: Bearer``. The token is
issued for the Public API's Auth0 API, the issuer and audience in
``PUBLIC_API_AUTH_ISSUER`` and ``PUBLIC_API_AUTH_AUDIENCE``, and is checked
by :func:`policyengine_api.libs.user_auth.authenticate_bearer`. Its client ID,
the subject without its ``@clients`` suffix, must be listed in
``PUBLIC_API_SERVER_CLIENT_IDS``: client IDs separated by commas, with no
spaces. An empty or unset list allows no client.

:func:`identify_caller` classifies one request's ``Authorization`` header:

- absent or blank: no credential (:attr:`CallerKind.NONE`);
- a valid token of a listed client: a server (:attr:`CallerKind.SERVER`),
  with its client ID;
- a valid token of a signed-in user: a user (:attr:`CallerKind.USER`). It is
  not a server credential; the user routes check it again themselves;
- anything else is refused with :class:`CredentialRefusedError`: another
  scheme, a token that fails signature or claim validation (an expired user
  token included), or a valid token of a client that is not listed.

A bearer token that cannot be checked, because the signing keys cannot be
fetched or the settings are missing or malformed, raises
:class:`CredentialCheckUnavailableError`.

``PUBLIC_API_SERVER_CREDENTIAL_REQUIRED`` switches enforcement on (``1``) or
off (``0``, empty or unset, the deployed default). With it on, the Public API
serves only server credentials outside its public routes
(:func:`load_server_credential_requirement`;
:mod:`policyengine_api.request_caller` applies it).

This module never logs or returns a token or a user's subject. A client ID is
returned only from a token whose signature and claims are valid.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from policyengine_api.libs.user_auth import (
    CLIENT_SUBJECT_SUFFIX,
    PUBLIC_API_AUTH_AUDIENCE_ENV,
    PUBLIC_API_AUTH_ISSUER_ENV,
    InvalidBearerTokenError,
    MissingBearerTokenError,
    PrincipalKind,
    TokenDecoder,
    UserAuthConfigurationError,
    UserAuthSettings,
    UserAuthUnavailableError,
    authenticate_bearer,
    load_user_auth_settings,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

PUBLIC_API_SERVER_CLIENT_IDS_ENV = "PUBLIC_API_SERVER_CLIENT_IDS"
PUBLIC_API_SERVER_CREDENTIAL_REQUIRED_ENV = "PUBLIC_API_SERVER_CREDENTIAL_REQUIRED"
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
    CREDENTIAL_REQUIRED = "credential_required"


@dataclass(frozen=True)
class RequestCaller:
    """The caller of one request; ``client_id`` is set only for a server."""

    kind: CallerKind
    client_id: str | None = None


NO_CREDENTIAL = RequestCaller(kind=CallerKind.NONE)
SIGNED_IN_USER = RequestCaller(kind=CallerKind.USER)


@dataclass(frozen=True)
class ServerCredentialSettings:
    """The client IDs whose client-credentials tokens are server credentials."""

    allowed_client_ids: frozenset[str]


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
    """Load and validate the allow list of server client IDs.

    Raise :class:`UserAuthConfigurationError` for a malformed list, or for a
    list without the Auth0 issuer and audience that check its clients' tokens.
    """
    values = os.environ if environ is None else environ
    allow_list = values.get(PUBLIC_API_SERVER_CLIENT_IDS_ENV, "")
    if not allow_list.strip():
        return ServerCredentialSettings(allowed_client_ids=frozenset())
    client_ids = allow_list.split(",")
    if not all(re.fullmatch(CLIENT_ID_PATTERN, client_id) for client_id in client_ids):
        msg = (
            f"{PUBLIC_API_SERVER_CLIENT_IDS_ENV} must be Auth0 client IDs "
            "separated by commas, with no spaces or empty entries"
        )
        raise UserAuthConfigurationError(msg)
    if not load_user_auth_settings(values).configured:
        msg = (
            f"{PUBLIC_API_SERVER_CLIENT_IDS_ENV} requires "
            f"{PUBLIC_API_AUTH_ISSUER_ENV} and {PUBLIC_API_AUTH_AUDIENCE_ENV}"
        )
        raise UserAuthConfigurationError(msg)
    return ServerCredentialSettings(allowed_client_ids=frozenset(client_ids))


def load_server_credential_requirement(
    environ: Mapping[str, str] | None = None,
) -> bool:
    """Return whether every non-public request needs a server credential.

    Raise :class:`UserAuthConfigurationError` for a value other than ``0``,
    ``1`` or empty, and for ``1`` without an allowed client, which would
    refuse every request.
    """
    values = os.environ if environ is None else environ
    requirement = values.get(PUBLIC_API_SERVER_CREDENTIAL_REQUIRED_ENV, "").strip()
    if requirement not in {"", "0", "1"}:
        msg = f"{PUBLIC_API_SERVER_CREDENTIAL_REQUIRED_ENV} must be 0 or 1"
        raise UserAuthConfigurationError(msg)
    if requirement != "1":
        return False
    if not load_server_credential_settings(values).allowed_client_ids:
        msg = (
            f"{PUBLIC_API_SERVER_CREDENTIAL_REQUIRED_ENV}=1 requires "
            f"{PUBLIC_API_SERVER_CLIENT_IDS_ENV}"
        )
        raise UserAuthConfigurationError(msg)
    return True


def _client_id(subject: str) -> str | None:
    """Return the client ID of a ``<client ID>@clients`` subject, or None."""
    if not subject.endswith(CLIENT_SUBJECT_SUFFIX):
        return None
    client_id = subject.removesuffix(CLIENT_SUBJECT_SUFFIX)
    return client_id if re.fullmatch(CLIENT_ID_PATTERN, client_id) else None


def identify_caller(
    authorization: str | None,
    auth_settings: UserAuthSettings,
    credential_settings: ServerCredentialSettings,
    *,
    decoder: TokenDecoder | None = None,
) -> RequestCaller:
    """Classify one ``Authorization`` header, or refuse it.

    Raise :class:`CredentialRefusedError` for a header that is not a valid
    credential, and :class:`CredentialCheckUnavailableError` for a bearer token
    that cannot be checked.
    """
    if authorization is None or not authorization.strip():
        return NO_CREDENTIAL
    try:
        principal = authenticate_bearer(authorization, auth_settings, decoder=decoder)
    except (MissingBearerTokenError, InvalidBearerTokenError) as error:
        raise CredentialRefusedError(RefusalReason.FAILED_VALIDATION) from error
    except UserAuthUnavailableError as error:
        msg = "the bearer token cannot be checked"
        raise CredentialCheckUnavailableError(msg) from error
    if principal.kind is PrincipalKind.USER:
        return SIGNED_IN_USER
    client_id = _client_id(principal.subject)
    if client_id is None:
        raise CredentialRefusedError(RefusalReason.FAILED_VALIDATION)
    if client_id not in credential_settings.allowed_client_ids:
        raise CredentialRefusedError(
            RefusalReason.CLIENT_NOT_ALLOWED, client_id=client_id
        )
    return RequestCaller(kind=CallerKind.SERVER, client_id=client_id)
