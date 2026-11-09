"""The Public API checks a server credential whenever a request carries one.

Every request goes through the ASGI application that production serves, to a
Flask route and to a native FastAPI route, with real RS256 tokens. A server
credential is an Auth0 client-credentials token whose client ID is in
``PUBLIC_API_SERVER_CLIENT_IDS``. Enforcement is not switched on here, so a
request without a credential is still served.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import Mock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from flask import Flask, jsonify

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.libs import user_auth
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.migration_logging import register_migration_request_logging
from policyengine_api.services.v2.countries.types import CountryRead

if TYPE_CHECKING:
    from collections.abc import Iterator

ISSUER = "https://auth.example.test/"
AUDIENCE = "https://api.policyengine.org/"
SERVER_CLIENT_IDS_ENV = "PUBLIC_API_SERVER_CLIENT_IDS"
ALLOWED_CLIENT_ID = "AllowedServerClient0000000000001"
SECOND_ALLOWED_CLIENT_ID = "AllowedServerClient0000000000002"
UNLISTED_CLIENT_ID = "UnlistedServerClient000000000003"
USER_SUBJECT = "google-oauth2|1234567890"
SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

FLASK_PATH = "/us/metadata"
NATIVE_PATH = "/v2/countries"
ROUTE_PATHS = pytest.mark.parametrize(
    "path", [FLASK_PATH, NATIVE_PATH], ids=["flask-route", "native-route"]
)

REFUSAL_BODY = b'{"status":"error","message":"Authentication is required"}'
UNAVAILABLE_BODY = {"status": "error", "message": "Authentication is unavailable"}
CREDENTIAL_LOGGER_NAMES = (
    "policyengine_api.request_caller",
    "policyengine_api.libs.server_credentials",
    "policyengine_api.libs.user_auth",
)


def _token(*, signing_key: rsa.RSAPrivateKey = SIGNING_KEY, **claims: object) -> str:
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


def _server_token(client_id: str = ALLOWED_CLIENT_ID, **claims: object) -> str:
    return _token(
        sub=f"{client_id}@clients",
        azp=client_id,
        gty="client-credentials",
        **claims,
    )


def _user_token(**claims: object) -> str:
    return _token(sub=USER_SUBJECT, azp="BrowserSignInClient0000000000004", **claims)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


EXPIRED = datetime.now(UTC) - timedelta(minutes=1)
REFUSED_AUTHORIZATION_HEADERS = {
    "bearer-not-a-jwt": "Bearer not-a-jwt",
    "bearer-without-a-token": "Bearer",
    "basic-scheme": "Basic dXNlcjpwYXNzd29yZA==",
    "expired-server-token": f"Bearer {_server_token(exp=EXPIRED)}",
    "server-token-for-another-audience": (
        f"Bearer {_server_token(aud='https://other-api.example.test/')}"
    ),
    "server-token-from-another-issuer": (
        f"Bearer {_server_token(iss='https://other-tenant.example.test/')}"
    ),
    "server-token-with-another-signing-key": (
        f"Bearer {_server_token(signing_key=OTHER_SIGNING_KEY)}"
    ),
    "unlisted-client": f"Bearer {_server_token(UNLISTED_CLIENT_ID)}",
    "client-grant-without-a-client-subject": (
        f"Bearer {_token(sub='not-a-client-subject', gty='client-credentials')}"
    ),
    "expired-user-token": f"Bearer {_user_token(exp=EXPIRED)}",
    "user-token-with-another-signing-key": (
        f"Bearer {_user_token(signing_key=OTHER_SIGNING_KEY)}"
    ),
    "hs256-token": "Bearer "
    + jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": f"{ALLOWED_CLIENT_ID}@clients"},
        "shared-secret-" * 4,
        algorithm="HS256",
    ),
}


class StaticJWKClient:
    """Serve one public key, or raise ``error``, without a network."""

    def __init__(self, error: Exception | None = None) -> None:
        self._public_key = SIGNING_KEY.public_key()
        self._error = error

    def get_signing_key_from_jwt(self, _token: str) -> SimpleNamespace:
        if self._error is not None:
            raise self._error
        return SimpleNamespace(key=self._public_key)


class FakeCountryService:
    def __init__(self) -> None:
        self.list_calls = 0

    def list_countries(self) -> list[CountryRead]:
        self.list_calls += 1
        return [CountryRead(id="us", household_enabled=True, society_wide_enabled=True)]


class RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def install_signing_keys(monkeypatch: pytest.MonkeyPatch):
    """Configure the Public API's Auth0 settings and its token decoder."""
    monkeypatch.setenv(user_auth.PUBLIC_API_AUTH_REQUIRED_ENV, "1")
    monkeypatch.setenv(user_auth.PUBLIC_API_AUTH_ISSUER_ENV, ISSUER)
    monkeypatch.setenv(user_auth.PUBLIC_API_AUTH_AUDIENCE_ENV, AUDIENCE)
    monkeypatch.setenv(
        SERVER_CLIENT_IDS_ENV, f"{ALLOWED_CLIENT_ID},{SECOND_ALLOWED_CLIENT_ID}"
    )

    def install(jwks_client: StaticJWKClient) -> None:
        decoder = user_auth.JWTDecoder(ISSUER, AUDIENCE, jwks_client=jwks_client)
        monkeypatch.setattr(user_auth, "_decoder", lambda _issuer, _audience: decoder)

    install(StaticJWKClient())
    return install


@pytest.fixture
def credential_log_records() -> Iterator[list[logging.LogRecord]]:
    """Record what the credential check logs.

    Alembic tests run logging.config.fileConfig, which disables loggers that
    already exist, so each logger is re-enabled while it is recorded.
    """
    handler = RecordingHandler()
    loggers = [logging.getLogger(name) for name in CREDENTIAL_LOGGER_NAMES]
    previous_states = [(logger.disabled, logger.level) for logger in loggers]
    for logger in loggers:
        logger.disabled = False
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        for logger, (was_disabled, level) in zip(loggers, previous_states, strict=True):
            logger.removeHandler(handler)
            logger.disabled = was_disabled
            logger.setLevel(level)


def _recording_runtime() -> Mock:
    runtime = Mock()
    runtime.begin_request.return_value = "request-id-0001"
    runtime.response_headers.return_value = {}
    runtime.capture_context.return_value = {}
    return runtime


def _application() -> SimpleNamespace:
    """Build the ASGI application around a Flask app, with a recording runtime."""
    runtime = _recording_runtime()
    flask_calls: list[str] = []
    flask_app = Flask(__name__)

    @flask_app.route("/<path:resource>", methods=["GET", "POST"])
    def fallback(resource: str):
        flask_calls.append(resource)
        return jsonify({"source": "flask"})

    register_migration_request_logging(flask_app, runtime=runtime)
    country_service = FakeCountryService()
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        v2_country_service_factory=lambda: country_service,
    )
    asgi_app = create_asgi_app(
        flask_app,
        dependencies=dependencies,
        route_settings=RouteImplementationSettings(
            health=RouteImplementation.FLASK_FALLBACK,
            specification=RouteImplementation.FLASK_FALLBACK,
            metadata=RouteImplementation.FLASK_FALLBACK,
        ),
        observability_runtime=runtime,
    )
    return SimpleNamespace(
        client=TestClient(asgi_app),
        runtime=runtime,
        flask_calls=flask_calls,
        country_service=country_service,
    )


def _recorded_caller(runtime: Mock) -> dict[str, object]:
    """Return the ``caller.*`` attributes a request added to its record."""
    recorded: dict[str, object] = {}
    for recorded_call in runtime.set_context.call_args_list:
        recorded.update(
            {
                name: value
                for name, value in recorded_call.kwargs.items()
                if name.startswith("caller.")
            }
        )
    return recorded


def _route_calls(application: SimpleNamespace) -> int:
    return len(application.flask_calls) + application.country_service.list_calls


def _assert_refused(response) -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["content-type"] == "application/json"
    assert response.content == REFUSAL_BODY


@ROUTE_PATHS
@pytest.mark.usefixtures("install_signing_keys")
def test_a_request_without_a_credential_is_served_and_recorded_without_warnings(
    path: str, credential_log_records: list[logging.LogRecord]
) -> None:
    application = _application()

    response = application.client.get(path)

    assert response.status_code == 200
    assert _route_calls(application) == 1
    assert _recorded_caller(application.runtime) == {"caller.kind": "none"}
    assert [
        record for record in credential_log_records if record.levelno > logging.INFO
    ] == []


@ROUTE_PATHS
@pytest.mark.usefixtures("install_signing_keys")
def test_an_empty_authorization_header_counts_as_no_credential(path: str) -> None:
    application = _application()

    response = application.client.get(path, headers={"Authorization": "  "})

    assert response.status_code == 200
    assert _recorded_caller(application.runtime) == {"caller.kind": "none"}


@ROUTE_PATHS
@pytest.mark.parametrize("client_id", [ALLOWED_CLIENT_ID, SECOND_ALLOWED_CLIENT_ID])
@pytest.mark.usefixtures("install_signing_keys")
def test_an_allowed_server_credential_is_served_and_its_client_recorded(
    path: str, client_id: str
) -> None:
    application = _application()

    response = application.client.get(path, headers=_bearer(_server_token(client_id)))

    assert response.status_code == 200
    assert _route_calls(application) == 1
    assert _recorded_caller(application.runtime) == {
        "caller.kind": "server",
        "caller.client_id": client_id,
    }


@ROUTE_PATHS
@pytest.mark.parametrize(
    "authorization",
    list(REFUSED_AUTHORIZATION_HEADERS.values()),
    ids=list(REFUSED_AUTHORIZATION_HEADERS),
)
@pytest.mark.usefixtures("install_signing_keys")
def test_a_credential_that_fails_validation_is_refused_before_the_route(
    path: str, authorization: str
) -> None:
    application = _application()

    response = application.client.get(path, headers={"Authorization": authorization})

    _assert_refused(response)
    assert _route_calls(application) == 0


@pytest.mark.usefixtures("install_signing_keys")
def test_every_allowed_client_is_refused_while_the_allow_list_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SERVER_CLIENT_IDS_ENV)
    application = _application()

    response = application.client.post(
        "/us/calculate", headers=_bearer(_server_token()), json={}
    )

    _assert_refused(response)
    assert application.flask_calls == []


@pytest.mark.usefixtures("install_signing_keys")
def test_a_cross_origin_browser_can_read_the_refusal() -> None:
    application = _application()

    response = application.client.get(
        FLASK_PATH,
        headers={"Origin": "https://example.test", "Authorization": "Bearer made-up"},
    )

    _assert_refused(response)
    assert response.headers["access-control-allow-origin"] == "https://example.test"
    exposed = {
        name.strip().lower()
        for name in response.headers["access-control-expose-headers"].split(",")
    }
    assert "www-authenticate" in exposed


@pytest.mark.usefixtures("install_signing_keys")
def test_two_authorization_headers_are_refused_even_when_one_is_valid() -> None:
    application = _application()

    response = application.client.get(
        FLASK_PATH,
        headers=[
            ("Authorization", f"Bearer {_server_token()}"),
            ("Authorization", "Bearer made-up"),
        ],
    )

    _assert_refused(response)
    assert application.flask_calls == []


@ROUTE_PATHS
@pytest.mark.usefixtures("install_signing_keys")
def test_a_signed_in_users_token_is_served_and_recorded_without_the_user(
    path: str,
) -> None:
    application = _application()

    response = application.client.get(path, headers=_bearer(_user_token()))

    assert response.status_code == 200
    assert _route_calls(application) == 1
    assert _recorded_caller(application.runtime) == {"caller.kind": "user"}
    assert USER_SUBJECT not in str(application.runtime.mock_calls)


@pytest.mark.usefixtures("install_signing_keys")
def test_refusals_are_logged_at_info_with_their_reason(
    credential_log_records: list[logging.LogRecord],
) -> None:
    application = _application()

    application.client.get(FLASK_PATH, headers={"Authorization": "Bearer made-up"})
    application.client.get(
        FLASK_PATH, headers=_bearer(_server_token(UNLISTED_CLIENT_ID))
    )

    refusals = [
        record
        for record in credential_log_records
        if record.getMessage() == "public_api_credential_refused"
    ]
    assert [record.levelno for record in refusals] == [logging.INFO, logging.INFO]
    assert refusals[0].policyengine_attributes == {
        "refusal_reason": "invalid_token",
        "http.request.method": "GET",
        "url.path": FLASK_PATH,
    }
    assert refusals[1].policyengine_attributes == {
        "refusal_reason": "client_not_allowed",
        "caller.client_id": UNLISTED_CLIENT_ID,
        "http.request.method": "GET",
        "url.path": FLASK_PATH,
    }
    assert all(record.levelno <= logging.INFO for record in credential_log_records)
    assert "made-up" not in str([vars(record) for record in credential_log_records])


@ROUTE_PATHS
def test_a_bearer_token_is_unavailable_when_signing_keys_cannot_be_fetched(
    path: str, install_signing_keys
) -> None:
    install_signing_keys(
        StaticJWKClient(error=jwt.PyJWKClientConnectionError("unreachable"))
    )
    application = _application()

    refused = application.client.get(path, headers=_bearer(_server_token()))
    served = application.client.get(path)

    assert refused.status_code == 503
    assert refused.json() == UNAVAILABLE_BODY
    assert served.status_code == 200
    assert _route_calls(application) == 1


@ROUTE_PATHS
@pytest.mark.usefixtures("install_signing_keys")
def test_a_bearer_token_is_unavailable_without_auth_settings(
    path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(SERVER_CLIENT_IDS_ENV)
    for name in user_auth.PUBLIC_API_AUTH_ENV_VARS:
        monkeypatch.delenv(name)
    application = _application()

    refused = application.client.get(path, headers=_bearer(_server_token()))
    served = application.client.get(path)

    assert refused.status_code == 503
    assert refused.json() == UNAVAILABLE_BODY
    assert served.status_code == 200
    assert _route_calls(application) == 1


@pytest.mark.usefixtures("install_signing_keys")
@pytest.mark.parametrize("allow_list", ["client-a,", "client-a client-b", ",client-a"])
def test_a_malformed_allow_list_makes_a_bearer_token_unavailable(
    allow_list: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(SERVER_CLIENT_IDS_ENV, allow_list)
    application = _application()

    refused = application.client.get(FLASK_PATH, headers=_bearer(_server_token()))
    served = application.client.get(FLASK_PATH)

    assert refused.status_code == 503
    assert refused.json() == UNAVAILABLE_BODY
    assert served.status_code == 200
