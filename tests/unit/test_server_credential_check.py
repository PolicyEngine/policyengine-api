"""The Public API checks a server credential whenever a request carries one.

Every request goes through the ASGI application that production serves, to a
Flask route and to a native FastAPI route, with real RS256 tokens. A server
credential is an Auth0 client-credentials token whose client ID is in
``PUBLIC_API_SERVER_CLIENT_IDS``. Enforcement is not switched on here, so a
request without a credential is still served.
"""

from __future__ import annotations

import logging
import ssl
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import Mock, create_autospec

import jwt
import pytest
from fastapi.testclient import TestClient
from flask import Flask, jsonify
from policyengine_observability import ObservabilityRuntime
from policyengine_observability.schema import normalize_attributes

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.libs import user_auth
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.migration_logging import register_migration_request_logging
from policyengine_api.observability import get_runtime
from policyengine_api.request_context import REQUEST_ID_HEADER
from policyengine_api.services.v2.countries.types import CountryRead
from tests.unit.credential_token_support import (
    ALLOWED_CLIENT_ID,
    AUDIENCE,
    EXPIRED,
    ISSUER,
    OTHER_SIGNING_KEY,
    SECOND_ALLOWED_CLIENT_ID,
    SERVER_CLIENT_IDS_ENV,
    UNLISTED_CLIENT_ID,
    USER_SUBJECT,
    StaticJWKClient,
    bearer,
    configure_credentials,
    install_token_decoder,
    server_token,
    signed_token,
    user_token,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

FLASK_PATH = "/us/metadata"
NATIVE_PATH = "/v2/countries"
ROUTE_PATHS = pytest.mark.parametrize(
    "path", [FLASK_PATH, NATIVE_PATH], ids=["flask-route", "native-route"]
)

REFUSAL_BODY = b'{"status":"error","message":"Authentication is required"}'
UNAVAILABLE_BODY = {"status": "error", "message": "Authentication is unavailable"}
CREDENTIAL_LOGGER_NAMES = (
    "policyengine_api.libs.server_credentials",
    "policyengine_api.libs.user_auth",
)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": bearer(token)}


# Each value is built when the test runs, so a token signed for ten minutes
# can't expire between collection and the test and pass for the wrong reason.
REFUSED_AUTHORIZATION_HEADERS: dict[str, Callable[[], str]] = {
    "bearer-not-a-jwt": lambda: "Bearer not-a-jwt",
    "no-break-space": lambda: "\xa0",
    "bearer-without-a-token": lambda: "Bearer",
    "basic-scheme": lambda: "Basic dXNlcjpwYXNzd29yZA==",
    "expired-server-token": lambda: bearer(server_token(exp=EXPIRED)),
    "server-token-for-another-audience": lambda: bearer(
        server_token(aud="https://other-api.example.test/")
    ),
    "server-token-from-another-issuer": lambda: bearer(
        server_token(iss="https://other-tenant.example.test/")
    ),
    "server-token-with-another-signing-key": lambda: bearer(
        server_token(signing_key=OTHER_SIGNING_KEY)
    ),
    "unlisted-client": lambda: bearer(server_token(UNLISTED_CLIENT_ID)),
    "user-subject-ending-in-clients": lambda: bearer(
        signed_token(sub="auth0|someone@clients")
    ),
    "client-grant-without-a-client-subject": lambda: bearer(
        signed_token(sub="not-a-client-subject", gty="client-credentials")
    ),
    "expired-user-token": lambda: bearer(user_token(exp=EXPIRED)),
    "user-token-with-another-signing-key": lambda: bearer(
        user_token(signing_key=OTHER_SIGNING_KEY)
    ),
    "hs256-token": lambda: bearer(
        jwt.encode(
            {"iss": ISSUER, "aud": AUDIENCE, "sub": f"{ALLOWED_CLIENT_ID}@clients"},
            "shared-secret-" * 4,
            algorithm="HS256",
        )
    ),
}


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
    """Configure the Public API's Auth0 settings, allow list and token decoder."""
    configure_credentials(monkeypatch)

    def install(jwks_client: StaticJWKClient) -> None:
        install_token_decoder(monkeypatch, jwks_client)

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
    # Checked against the runtime's own signatures, so a changed call fails.
    runtime = create_autospec(ObservabilityRuntime, instance=True)
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


def _credential_events(runtime: Mock) -> list[tuple[str, str, dict[str, object]]]:
    """Return the credential check's runtime events as (name, severity, attributes)."""
    return [
        (
            recorded_call.args[0],
            recorded_call.kwargs["severity"],
            recorded_call.kwargs["attributes"],
        )
        for recorded_call in runtime.event.call_args_list
        if recorded_call.args
        and str(recorded_call.args[0]).startswith("public_api_credential")
    ]


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
    assert _credential_events(application.runtime) == []
    assert [
        record for record in credential_log_records if record.levelno > logging.INFO
    ] == []


@ROUTE_PATHS
@pytest.mark.usefixtures("install_signing_keys")
def test_an_empty_authorization_header_counts_as_no_credential(path: str) -> None:
    application = _application()

    response = application.client.get(path, headers={"Authorization": " \t "})

    assert response.status_code == 200
    assert _recorded_caller(application.runtime) == {"caller.kind": "none"}


@ROUTE_PATHS
@pytest.mark.parametrize("client_id", [ALLOWED_CLIENT_ID, SECOND_ALLOWED_CLIENT_ID])
@pytest.mark.usefixtures("install_signing_keys")
def test_an_allowed_server_credential_is_served_and_its_client_recorded(
    path: str, client_id: str
) -> None:
    application = _application()

    response = application.client.get(path, headers=_bearer(server_token(client_id)))

    assert response.status_code == 200
    assert _route_calls(application) == 1
    assert _recorded_caller(application.runtime) == {
        "caller.kind": "server",
        "caller.client_id": client_id,
    }


@ROUTE_PATHS
@pytest.mark.parametrize(
    "build_authorization",
    list(REFUSED_AUTHORIZATION_HEADERS.values()),
    ids=list(REFUSED_AUTHORIZATION_HEADERS),
)
@pytest.mark.usefixtures("install_signing_keys")
def test_a_credential_that_fails_validation_is_refused_before_the_route(
    path: str, build_authorization: Callable[[], str]
) -> None:
    application = _application()

    # Sent as Latin-1 bytes, as HTTP carries them, so a no-break space can be.
    response = application.client.get(
        path, headers={"Authorization": build_authorization().encode("latin-1")}
    )

    _assert_refused(response)
    assert _route_calls(application) == 0


@pytest.mark.usefixtures("install_signing_keys")
def test_every_allowed_client_is_refused_while_the_allow_list_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SERVER_CLIENT_IDS_ENV)
    application = _application()

    response = application.client.post(
        "/us/calculate", headers=_bearer(server_token()), json={}
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
            ("Authorization", f"Bearer {server_token()}"),
            ("Authorization", "Bearer made-up"),
        ],
    )

    _assert_refused(response)
    assert application.flask_calls == []
    assert [
        attributes["refusal_reason"]
        for _name, _severity, attributes in _credential_events(application.runtime)
    ] == ["duplicate_authorization_header"]


@ROUTE_PATHS
@pytest.mark.usefixtures("install_signing_keys")
def test_a_signed_in_users_token_is_served_and_recorded_without_the_user(
    path: str,
) -> None:
    application = _application()

    response = application.client.get(path, headers=_bearer(user_token()))

    assert response.status_code == 200
    assert _route_calls(application) == 1
    assert _recorded_caller(application.runtime) == {"caller.kind": "user"}
    assert USER_SUBJECT not in str(application.runtime.mock_calls)


@pytest.mark.usefixtures("install_signing_keys")
def test_every_refusal_is_recorded_at_info_with_its_reason_and_request_id() -> None:
    """Refusals reach the runtime directly, whatever the logging levels.

    A refused request to a Flask route never reaches Flask, so this event is
    its only record; it carries the request ID the response returns.
    """
    application = _application()

    made_up = application.client.get(
        FLASK_PATH, headers={"Authorization": "Bearer made-up"}
    )
    unlisted = application.client.get(
        NATIVE_PATH, headers=_bearer(server_token(UNLISTED_CLIENT_ID))
    )

    assert _credential_events(application.runtime) == [
        (
            "public_api_credential_refused",
            "INFO",
            {
                "refusal_reason": "invalid_token",
                "http.request.method": "GET",
                "url.path": FLASK_PATH,
                "request.id": made_up.headers[REQUEST_ID_HEADER],
            },
        ),
        (
            "public_api_credential_refused",
            "INFO",
            {
                "refusal_reason": "client_not_allowed",
                "caller.client_id": UNLISTED_CLIENT_ID,
                "http.request.method": "GET",
                "url.path": NATIVE_PATH,
                "request.id": unlisted.headers[REQUEST_ID_HEADER],
            },
        ),
    ]
    assert "made-up" not in str(application.runtime.event.call_args_list)


@ROUTE_PATHS
@pytest.mark.usefixtures("install_signing_keys")
def test_a_malformed_host_header_still_gets_the_refusal(path: str) -> None:
    # Starlette builds request.url from Host; "[" makes it raise. The client
    # returns a server error as a response, so the status is what is checked.
    application = _application()
    client = TestClient(application.client.app, raise_server_exceptions=False)

    response = client.get(
        path, headers={"Host": "[", "Authorization": "Bearer made-up"}
    )

    _assert_refused(response)
    ((_severity, attributes),) = [
        (severity, recorded_attributes)
        for _name, severity, recorded_attributes in _credential_events(
            application.runtime
        )
    ]
    assert attributes["url.path"] == path


@pytest.mark.usefixtures("install_signing_keys")
def test_a_refusal_records_the_decoded_path_the_routers_match() -> None:
    application = _application()

    application.client.get(
        "/us/metadata%3Fpart",
        headers={"Host": "api.example.test/v2/me?", "Authorization": "Bearer made-up"},
    )

    ((_name, _severity, attributes),) = _credential_events(application.runtime)
    assert attributes["url.path"] == "/us/metadata?part"


@ROUTE_PATHS
def test_a_bearer_token_is_unavailable_when_signing_keys_cannot_be_fetched(
    path: str, install_signing_keys
) -> None:
    install_signing_keys(
        StaticJWKClient(error=jwt.PyJWKClientConnectionError("unreachable"))
    )
    application = _application()

    refused = application.client.get(path, headers=_bearer(server_token()))
    served = application.client.get(path)

    assert refused.status_code == 503
    assert refused.json() == UNAVAILABLE_BODY
    assert served.status_code == 200
    assert _route_calls(application) == 1
    assert _credential_events(application.runtime) == [
        (
            "public_api_credential_check_unavailable",
            "WARNING",
            {
                "error_type": "CredentialCheckUnavailableError",
                "http.request.method": "GET",
                "url.path": path,
                "request.id": refused.headers[REQUEST_ID_HEADER],
            },
        )
    ]


@pytest.mark.parametrize(
    "fetch_error",
    [
        ConnectionResetError("connection reset"),
        ssl.SSLError("bad record"),
        TimeoutError("read timed out"),
    ],
    ids=["connection-reset", "tls-error", "timeout"],
)
@ROUTE_PATHS
def test_a_signing_key_fetch_error_pyjwt_does_not_wrap_is_unavailable(
    path: str, fetch_error: OSError, install_signing_keys
) -> None:
    # urllib leaves errors from reading the response unwrapped, and PyJWT
    # converts only some of them; each must still answer 503, not 500.
    install_signing_keys(StaticJWKClient(error=fetch_error))
    application = _application()
    client = TestClient(application.client.app, raise_server_exceptions=False)

    refused = client.get(path, headers=_bearer(server_token()))

    assert refused.status_code == 503
    assert refused.json() == UNAVAILABLE_BODY
    assert [
        (name, severity)
        for name, severity, _attributes in _credential_events(application.runtime)
    ] == [("public_api_credential_check_unavailable", "WARNING")]


@ROUTE_PATHS
@pytest.mark.usefixtures("install_signing_keys")
def test_a_bearer_token_is_unavailable_without_auth_settings(
    path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(SERVER_CLIENT_IDS_ENV)
    for name in user_auth.PUBLIC_API_AUTH_ENV_VARS:
        monkeypatch.delenv(name)
    application = _application()

    refused = application.client.get(path, headers=_bearer(server_token()))
    served = application.client.get(path)

    assert refused.status_code == 503
    assert refused.json() == UNAVAILABLE_BODY
    assert served.status_code == 200
    assert _route_calls(application) == 1
    assert [
        (name, severity, attributes["error_type"])
        for name, severity, attributes in _credential_events(application.runtime)
    ] == [
        (
            "public_api_credential_check_unavailable",
            "WARNING",
            "CredentialCheckUnavailableError",
        )
    ]


@pytest.mark.usefixtures("install_signing_keys")
@pytest.mark.parametrize("allow_list", ["client-a,", "client-a client-b", ",client-a"])
def test_a_malformed_allow_list_makes_a_bearer_token_unavailable(
    allow_list: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(SERVER_CLIENT_IDS_ENV, allow_list)
    application = _application()

    refused = application.client.get(FLASK_PATH, headers=_bearer(server_token()))
    served = application.client.get(FLASK_PATH)

    assert refused.status_code == 503
    assert refused.json() == UNAVAILABLE_BODY
    assert served.status_code == 200
    assert [
        (name, severity, attributes["error_type"])
        for name, severity, attributes in _credential_events(application.runtime)
    ] == [
        (
            "public_api_credential_check_unavailable",
            "WARNING",
            "UserAuthConfigurationError",
        )
    ]


def test_recorded_attributes_survive_the_runtimes_attribute_rules(
    install_signing_keys,
) -> None:
    """The runtime drops attributes whose names contain parts such as "token".

    A Mock runtime accepts any name, so each recorded name is checked against
    the configured runtime's own rules.
    """
    application = _application()
    application.client.get(FLASK_PATH, headers=_bearer(server_token()))
    application.client.get(FLASK_PATH, headers={"Authorization": "Bearer made-up"})
    application.client.get(
        FLASK_PATH, headers=_bearer(server_token(UNLISTED_CLIENT_ID))
    )
    install_signing_keys(
        StaticJWKClient(error=jwt.PyJWKClientConnectionError("unreachable"))
    )
    application.client.get(NATIVE_PATH, headers=_bearer(server_token()))

    recorded = [
        attributes
        for _name, _severity, attributes in _credential_events(application.runtime)
    ] + [_recorded_caller(application.runtime)]
    config = get_runtime().config
    assert len(recorded) == 4
    for attributes in recorded:
        normalized, omitted = normalize_attributes(
            attributes, config, allowed_keys=config.local_attribute_keys
        )
        assert omitted == 0
        assert normalized == attributes
