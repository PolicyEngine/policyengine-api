"""With enforcement on, the Public API serves only server credentials.

``PUBLIC_API_SERVER_CREDENTIAL_REQUIRED=1`` refuses every request without a
valid server credential before route matching, so ``/`` and unknown paths
are refused too. Only ``GET`` and ``HEAD /health``, ``GET /v2/openapi.json``
and CORS preflights answer without one; Cloud Run's startup probe calls
``/health`` on the container directly. Requests go through the ASGI
application that production serves, with real RS256 tokens.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from flask import Flask, jsonify
from starlette.requests import Request

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.migration_logging import register_migration_request_logging
from policyengine_api.request_caller import is_public_request
from policyengine_api.request_context import REQUEST_ID_HEADER
from policyengine_api.services.v2.countries.types import CountryRead
from tests.unit.credential_token_support import (
    SERVER_CLIENT_IDS_ENV,
    bearer,
    configure_credentials,
    server_token,
    user_token,
)

ENFORCEMENT_ENV = "PUBLIC_API_SERVER_CREDENTIAL_REQUIRED"
REFUSAL_BODY = b'{"status":"error","message":"Authentication is required"}'
NON_PUBLIC_REQUESTS = [
    ("GET", "/us/metadata"),
    ("POST", "/us/calculate"),
    ("GET", "/v2/countries"),
    ("GET", "/"),
    ("GET", "/no-such-route"),
    ("GET", "/v2/no-such-resource"),
    # Only the exact public routes, with their methods, are public.
    ("POST", "/health"),
    ("GET", "/health/"),
    ("GET", "/HEALTH"),
    ("GET", "/health-and-more"),
    ("HEAD", "/v2/openapi.json"),
    ("POST", "/v2/openapi.json"),
    ("GET", "/v2/openapi.json/"),
    ("GET", "/openapi.json"),
    # An OPTIONS request that is not a CORS preflight.
    ("OPTIONS", "/us/metadata"),
]


class FakeCountryService:
    def __init__(self) -> None:
        self.list_calls = 0

    def list_countries(self) -> list[CountryRead]:
        self.list_calls += 1
        return [CountryRead(id="us", household_enabled=True, society_wide_enabled=True)]


@pytest.fixture
def enforcement_on(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_credentials(monkeypatch)
    monkeypatch.setenv(ENFORCEMENT_ENV, "1")


def _application() -> SimpleNamespace:
    """Build the ASGI application around a Flask app that serves any path."""
    runtime = Mock()
    runtime.begin_request.return_value = "request-id-0002"
    runtime.response_headers.return_value = {}
    runtime.capture_context.return_value = {}
    flask_calls: list[str] = []
    flask_app = Flask(__name__)

    @flask_app.route("/", defaults={"resource": ""}, methods=["GET", "POST"])
    @flask_app.route("/<path:resource>", methods=["GET", "POST", "HEAD"])
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
            health=RouteImplementation.FASTAPI_NATIVE,
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


def _refusal_events(runtime: Mock) -> list[tuple[str, dict[str, object]]]:
    """Return the runtime's refusal events as (severity, attributes)."""
    return [
        (recorded_call.kwargs["severity"], recorded_call.kwargs["attributes"])
        for recorded_call in runtime.event.call_args_list
        if recorded_call.args == ("public_api_credential_refused",)
    ]


def _route_calls(application: SimpleNamespace) -> int:
    return len(application.flask_calls) + application.country_service.list_calls


def _assert_refused(response, method: str = "GET") -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["content-type"] == "application/json"
    # A response to HEAD has the headers of the refusal but no body.
    assert response.content == (b"" if method == "HEAD" else REFUSAL_BODY)


@pytest.mark.parametrize(("method", "path"), NON_PUBLIC_REQUESTS)
@pytest.mark.usefixtures("enforcement_on")
def test_enforcement_refuses_every_request_without_a_credential_before_routing(
    method: str, path: str
) -> None:
    application = _application()

    response = application.client.request(method, path)

    _assert_refused(response, method)
    assert _route_calls(application) == 0


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.usefixtures("enforcement_on")
def test_enforcement_leaves_the_health_check_public(method: str) -> None:
    # /health is always a native route (see migration_flags).
    application = _application()

    response = application.client.request(method, "/health")

    assert response.status_code == 200


@pytest.mark.usefixtures("enforcement_on")
def test_enforcement_leaves_the_v2_openapi_schema_public() -> None:
    application = _application()

    response = application.client.get("/v2/openapi.json")

    assert response.status_code == 200
    assert response.json()["openapi"].startswith("3.")


@pytest.mark.usefixtures("enforcement_on")
def test_enforcement_leaves_cors_preflights_public() -> None:
    application = _application()

    response = application.client.options(
        "/us/calculate",
        headers={
            "Origin": "https://www.policyengine.org",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"]
        == "https://www.policyengine.org"
    )
    assert _route_calls(application) == 0


@pytest.mark.usefixtures("enforcement_on")
def test_enforcement_refuses_an_options_request_without_an_origin() -> None:
    # Without Origin it is not a CORS preflight, so it gets no exemption.
    application = _application()

    response = application.client.options(
        "/us/calculate", headers={"Access-Control-Request-Method": "POST"}
    )

    _assert_refused(response)
    assert _route_calls(application) == 0


@pytest.mark.parametrize(
    ("method", "path", "expected_status"),
    [
        ("GET", "/us/metadata", 200),
        ("POST", "/us/calculate", 200),
        ("GET", "/v2/countries", 200),
        ("GET", "/v2/no-such-resource", 404),
    ],
)
@pytest.mark.usefixtures("enforcement_on")
def test_enforcement_serves_an_allowed_server_credential(
    method: str, path: str, expected_status: int
) -> None:
    application = _application()

    response = application.client.request(
        method, path, headers={"Authorization": bearer(server_token())}
    )

    assert response.status_code == expected_status


@pytest.mark.usefixtures("enforcement_on")
def test_enforcement_refuses_a_signed_in_users_own_token() -> None:
    application = _application()

    response = application.client.get(
        "/v2/countries", headers={"Authorization": bearer(user_token())}
    )

    _assert_refused(response)
    assert _route_calls(application) == 0
    assert _refusal_events(application.runtime) == [
        (
            "INFO",
            {
                "refusal_reason": "credential_required",
                "caller.kind": "user",
                "http.request.method": "GET",
                "url.path": "/v2/countries",
                "request.id": response.headers[REQUEST_ID_HEADER],
            },
        )
    ]


@pytest.mark.usefixtures("enforcement_on")
def test_enforcement_records_a_refused_request_without_a_credential_at_info() -> None:
    application = _application()

    response = application.client.post("/us/calculate", json={})

    assert _refusal_events(application.runtime) == [
        (
            "INFO",
            {
                "refusal_reason": "credential_required",
                "caller.kind": "none",
                "http.request.method": "POST",
                "url.path": "/us/calculate",
                "request.id": response.headers[REQUEST_ID_HEADER],
            },
        )
    ]


@pytest.mark.parametrize("setting", [None, "", "0"], ids=["unset", "empty", "zero"])
def test_without_enforcement_a_request_without_a_credential_is_served(
    setting: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_credentials(monkeypatch)
    if setting is None:
        monkeypatch.delenv(ENFORCEMENT_ENV, raising=False)
    else:
        monkeypatch.setenv(ENFORCEMENT_ENV, setting)
    application = _application()

    responses = [
        application.client.get("/us/metadata"),
        application.client.get("/v2/countries"),
        application.client.get("/"),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200]


@pytest.mark.parametrize("setting", ["true", "yes", "2", "on"])
def test_a_malformed_enforcement_setting_fails_closed(
    setting: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_credentials(monkeypatch)
    monkeypatch.setenv(ENFORCEMENT_ENV, setting)
    application = _application()

    refused = application.client.get("/us/metadata")
    health = application.client.get("/health")
    served = application.client.get(
        "/us/metadata", headers={"Authorization": bearer(server_token())}
    )

    assert refused.status_code == 503
    assert health.status_code == 200
    assert served.status_code == 200
    assert [
        (recorded_call.args, recorded_call.kwargs)
        for recorded_call in application.runtime.event.call_args_list
    ] == [
        (
            ("public_api_credential_check_unavailable",),
            {
                "severity": "WARNING",
                "attributes": {
                    "error_type": "UserAuthConfigurationError",
                    "http.request.method": "GET",
                    "url.path": "/us/metadata",
                    "request.id": refused.headers[REQUEST_ID_HEADER],
                },
            },
        )
    ]


@pytest.mark.parametrize(
    ("method", "headers", "public"),
    [
        (
            "OPTIONS",
            {"origin": "https://example.test", "access-control-request-method": "POST"},
            True,
        ),
        ("OPTIONS", {"origin": "https://example.test"}, False),
        ("OPTIONS", {"access-control-request-method": "POST"}, False),
        ("OPTIONS", {}, False),
        (
            "POST",
            {"origin": "https://example.test", "access-control-request-method": "POST"},
            False,
        ),
    ],
    ids=["preflight", "origin-only", "method-only", "plain", "not-options"],
)
def test_only_a_cors_preflight_is_public_among_options_requests(
    method: str, headers: dict[str, str], *, public: bool
) -> None:
    # The CORS middleware answers browser preflights before the check, so
    # the preflight branch is tested on the check's own function.
    request = Request(
        {
            "type": "http",
            "method": method,
            "path": "/us/calculate",
            "headers": [
                (name.encode("latin-1"), value.encode("latin-1"))
                for name, value in headers.items()
            ],
        }
    )

    assert is_public_request(request) is public


def test_enforcement_with_an_empty_allow_list_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_credentials(monkeypatch, allowed_client_ids=())
    monkeypatch.delenv(SERVER_CLIENT_IDS_ENV)
    monkeypatch.setenv(ENFORCEMENT_ENV, "1")
    application = _application()

    refused = application.client.get("/us/metadata")
    health = application.client.get("/health")

    assert refused.status_code == 503
    assert health.status_code == 200
