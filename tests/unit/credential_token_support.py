"""Real RS256 Auth0-style tokens for tests of the Public API's credential checks.

There are two issuers, as in production: the signed-in users' tenant
(``ISSUER``) and the Public API's own tenant for server clients
(``SERVER_ISSUER``). Each signs with its own key, generated for the test run,
and :func:`install_token_decoder` makes the Public API verify each issuer's
tokens with its key's public half, without a network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from policyengine_api.libs import user_auth

if TYPE_CHECKING:
    import pytest

ISSUER = "https://auth.example.test/"
SERVER_ISSUER = "https://server-auth.example.test/"
AUDIENCE = "https://api.policyengine.org/"
SERVER_CLIENT_IDS_ENV = "PUBLIC_API_SERVER_CLIENT_IDS"
SERVER_ISSUER_ENV = "PUBLIC_API_SERVER_AUTH_ISSUER"
ALLOWED_CLIENT_ID = "AllowedServerClient0000000000001"
SECOND_ALLOWED_CLIENT_ID = "AllowedServerClient0000000000002"
UNLISTED_CLIENT_ID = "UnlistedServerClient000000000003"
BROWSER_SIGN_IN_CLIENT_ID = "BrowserSignInClient0000000000004"
USER_SUBJECT = "google-oauth2|1234567890"
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SERVER_SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
EXPIRED = datetime.now(UTC) - timedelta(minutes=1)


def signed_token(
    *, signing_key: rsa.RSAPrivateKey = SIGNING_KEY, **claims: object
) -> str:
    """Return an RS256 token for the test issuer and audience; None drops a claim."""
    issued_at = datetime.now(UTC)
    payload: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=10),
    }
    payload.update(claims)
    present_claims = {
        name: value for name, value in payload.items() if value is not None
    }
    return jwt.encode(present_claims, signing_key, algorithm="RS256")


def server_token(
    client_id: str = ALLOWED_CLIENT_ID,
    *,
    signing_key: rsa.RSAPrivateKey = SERVER_SIGNING_KEY,
    **claims: object,
) -> str:
    """Return an Auth0 client-credentials token of ``client_id``.

    By default it comes from the Public API's own tenant (``SERVER_ISSUER``).
    """
    return signed_token(
        signing_key=signing_key,
        **{
            "iss": SERVER_ISSUER,
            "sub": f"{client_id}@clients",
            "azp": client_id,
            "gty": "client-credentials",
            **claims,
        },
    )


def user_token(subject: str = USER_SUBJECT, **claims: object) -> str:
    """Return a signed-in user's Auth0 access token."""
    return signed_token(sub=subject, azp=BROWSER_SIGN_IN_CLIENT_ID, **claims)


def bearer(token: str) -> str:
    """Return an ``Authorization``-style value carrying ``token``."""
    return f"Bearer {token}"


class StaticJWKClient:
    """Serve one signing key's public half, or raise ``error``."""

    def __init__(
        self,
        error: Exception | None = None,
        *,
        signing_key: rsa.RSAPrivateKey = SIGNING_KEY,
    ) -> None:
        """Serve ``signing_key``'s public half, or raise ``error`` for every token."""
        self._public_key = signing_key.public_key()
        self._error = error

    def get_signing_key_from_jwt(self, _token: str) -> SimpleNamespace:
        """Return the public key the way PyJWKClient does."""
        if self._error is not None:
            raise self._error
        return SimpleNamespace(key=self._public_key)


def configure_credentials(
    monkeypatch: pytest.MonkeyPatch,
    allowed_client_ids: tuple[str, ...] = (ALLOWED_CLIENT_ID, SECOND_ALLOWED_CLIENT_ID),
) -> None:
    """Set both issuers, the audience and the allow list, with the test keys."""
    monkeypatch.setenv(user_auth.PUBLIC_API_AUTH_REQUIRED_ENV, "1")
    monkeypatch.setenv(user_auth.PUBLIC_API_AUTH_ISSUER_ENV, ISSUER)
    monkeypatch.setenv(user_auth.PUBLIC_API_AUTH_AUDIENCE_ENV, AUDIENCE)
    monkeypatch.setenv(SERVER_ISSUER_ENV, SERVER_ISSUER)
    monkeypatch.setenv(SERVER_CLIENT_IDS_ENV, ",".join(allowed_client_ids))
    install_token_decoder(monkeypatch)


def install_token_decoder(
    monkeypatch: pytest.MonkeyPatch, jwks_client: StaticJWKClient | None = None
) -> None:
    """Verify each issuer's tokens with its own key, or both with ``jwks_client``."""
    jwks_clients = {
        ISSUER: jwks_client or StaticJWKClient(signing_key=SIGNING_KEY),
        SERVER_ISSUER: jwks_client or StaticJWKClient(signing_key=SERVER_SIGNING_KEY),
    }
    decoders = {
        issuer: user_auth.JWTDecoder(issuer, AUDIENCE, jwks_client=client)
        for issuer, client in jwks_clients.items()
    }
    monkeypatch.setattr(
        user_auth, "_decoder", lambda issuer, _audience: decoders[issuer]
    )
