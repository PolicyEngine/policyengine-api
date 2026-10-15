"""Unit tests for :mod:`policyengine_api.libs.user_auth` with real RS256 tokens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from policyengine_api.libs.user_auth import (
    InvalidBearerTokenError,
    InvalidUnauthenticatedUserError,
    JWTDecoder,
    MissingBearerTokenError,
    PrincipalKind,
    UserAuthConfigurationError,
    UserAuthSettings,
    UserAuthUnavailableError,
    _normalized_issuer,
    authenticate_bearer,
    load_user_auth_settings,
    unauthenticated_user_id,
)

ISSUER = "https://auth.example.test/"
AUDIENCE = "https://api.policyengine.org/"
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StaticJWKClient:
    """Stand-in for PyJWKClient that serves one public key without network."""

    def __init__(self, private_key=SIGNING_KEY, error: Exception | None = None):
        self._public_key = private_key.public_key()
        self._error = error

    def get_signing_key_from_jwt(self, _token: str):
        if self._error is not None:
            raise self._error
        return SimpleNamespace(key=self._public_key)


def _token(*, key=SIGNING_KEY, algorithm: str = "RS256", **claims) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": ISSUER,
        "aud": [AUDIENCE, f"{ISSUER}userinfo"],
        "sub": "google-oauth2|1234",
        "iat": now,
        "exp": now + timedelta(minutes=10),
    }
    payload.update(claims)
    payload = {name: value for name, value in payload.items() if value is not None}
    return jwt.encode(payload, key, algorithm=algorithm)


def _settings(issuer: str = ISSUER) -> UserAuthSettings:
    return load_user_auth_settings(
        {
            "PUBLIC_API_AUTH_REQUIRED": "1",
            "PUBLIC_API_AUTH_ISSUER": issuer,
            "PUBLIC_API_AUTH_AUDIENCE": AUDIENCE,
        }
    )


def _authenticate(token: str, *, settings: UserAuthSettings | None = None, **client):
    selected = settings or _settings()
    decoder = JWTDecoder(
        selected.issuer,
        selected.audience,
        jwks_client=StaticJWKClient(**client),
    )
    return authenticate_bearer(f"Bearer {token}", selected, decoder=decoder)


def test_valid_user_token_yields_a_user_principal() -> None:
    principal = _authenticate(_token())

    assert principal.kind is PrincipalKind.USER
    assert principal.issuer == ISSUER
    assert principal.subject == "google-oauth2|1234"
    assert principal.email is None


def test_issuer_configured_without_a_trailing_slash_is_normalized() -> None:
    settings = _settings("https://auth.example.test")

    assert settings.issuer == ISSUER
    assert _normalized_issuer("https://auth.example.test//") == ISSUER
    assert _authenticate(_token(), settings=settings).issuer == ISSUER


@pytest.mark.parametrize(
    "token",
    [
        _token(exp=datetime.now(UTC) - timedelta(minutes=1)),
        _token(aud="https://other-api.example.test/"),
        _token(iss="https://evil.example.test/"),
        _token(iss=ISSUER.rstrip("/")),
        _token(key=OTHER_KEY),
        _token(sub=None),
        _token(exp=None),
        jwt.encode({"iss": ISSUER, "sub": "x"}, "h" * 32, algorithm="HS256"),
        "not-a-jwt",
    ],
    ids=[
        "expired",
        "wrong-audience",
        "wrong-issuer",
        "issuer-without-slash",
        "wrong-key",
        "missing-subject",
        "missing-expiry",
        "hs256",
        "malformed",
    ],
)
def test_invalid_tokens_are_rejected(token: str) -> None:
    with pytest.raises(InvalidBearerTokenError):
        _authenticate(token)


def test_client_credentials_tokens_are_client_principals() -> None:
    by_subject = _authenticate(_token(sub="abc123@clients"))
    by_grant = _authenticate(_token(sub="abc123", gty="client-credentials"))

    assert by_subject.kind is PrincipalKind.CLIENT
    assert by_grant.kind is PrincipalKind.CLIENT


def test_email_is_kept_only_when_verified() -> None:
    verified = _authenticate(_token(email="ada@example.com", email_verified=True))
    unverified = _authenticate(_token(email="ada@example.com", email_verified=False))
    string_flag = _authenticate(_token(email="ada@example.com", email_verified="true"))

    assert verified.email == "ada@example.com"
    assert unverified.email is None
    assert string_flag.email is None


@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer   ", "Basic abc"])
def test_missing_bearer_tokens_are_reported_before_configuration(header) -> None:
    with pytest.raises(MissingBearerTokenError):
        authenticate_bearer(
            header, UserAuthSettings(required=False, issuer="", audience="")
        )


def test_unconfigured_or_unreachable_key_sets_are_unavailable() -> None:
    with pytest.raises(UserAuthUnavailableError):
        authenticate_bearer(
            "Bearer token", UserAuthSettings(required=False, issuer="", audience="")
        )
    with pytest.raises(UserAuthUnavailableError):
        _authenticate(_token(), error=jwt.PyJWKClientConnectionError("down"))


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({"PUBLIC_API_AUTH_REQUIRED": "yes"}, "must be 0 or 1"),
        ({"PUBLIC_API_AUTH_REQUIRED": "1"}, "requires"),
        ({"PUBLIC_API_AUTH_ISSUER": ISSUER}, "Set both"),
        ({"PUBLIC_API_AUTH_AUDIENCE": AUDIENCE}, "Set both"),
        (
            {
                "PUBLIC_API_AUTH_ISSUER": "http://auth.example.test/",
                "PUBLIC_API_AUTH_AUDIENCE": AUDIENCE,
            },
            "HTTPS",
        ),
        (
            {
                "PUBLIC_API_AUTH_ISSUER": "https://auth.example.test/?x=1",
                "PUBLIC_API_AUTH_AUDIENCE": AUDIENCE,
            },
            "HTTPS",
        ),
    ],
)
def test_settings_fail_closed_when_inconsistent(environ, message: str) -> None:
    with pytest.raises(UserAuthConfigurationError, match=message):
        load_user_auth_settings(environ)


def test_settings_allow_an_explicitly_disabled_deployment() -> None:
    settings = load_user_auth_settings({"PUBLIC_API_AUTH_REQUIRED": "0"})

    assert settings == UserAuthSettings(required=False, issuer="", audience="")
    assert not settings.configured
    assert issubclass(UserAuthConfigurationError, RuntimeError)


def test_decoder_uses_the_issuer_jwks_endpoint() -> None:
    decoder = JWTDecoder(ISSUER, AUDIENCE)

    assert decoder.jwks_client.uri == f"{ISSUER}.well-known/jwks.json"


def test_unauthenticated_user_ids_are_canonical_uuids() -> None:
    browser_user_id = "8f14e45f-ceea-467a-9575-0b2c5c1c2f2a"

    assert unauthenticated_user_id(browser_user_id) == UUID(browser_user_id)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-uuid",
        "8F14E45F-CEEA-467A-9575-0B2C5C1C2F2A",
        "8f14e45fceea467a95750b2c5c1c2f2a",
        "{8f14e45f-ceea-467a-9575-0b2c5c1c2f2a}",
        "urn:uuid:8f14e45f-ceea-467a-9575-0b2c5c1c2f2a",
        "8f14e45f-ceea-467a-9575-0b2c5c1c2f2a\n",
    ],
)
def test_non_canonical_unauthenticated_user_ids_are_rejected(value: str) -> None:
    with pytest.raises(InvalidUnauthenticatedUserError) as raised:
        unauthenticated_user_id(value)

    assert value.strip() not in str(raised.value) or not value.strip()
