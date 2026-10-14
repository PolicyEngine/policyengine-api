"""Router-level authentication for every signed-in user route."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

import pytest

from policyengine_api.libs import user_auth
from policyengine_api.services.v2.identity.types import (
    UnauthenticatedPrincipal,
    UserPrincipal,
)
from policyengine_api.services.v2.user_accounts.types import AccountExport
from policyengine_api.services.v2.user_policies.types import UserPolicyPage
from tests.unit.v2.user_route_support import RecordingService, user_route_client


ISSUER = "https://auth.example.test/"
AUDIENCE = "https://api.policyengine.org/"
ASSOCIATION_ID = "00000000-0000-0000-0000-000000000001"
BROWSER_USER_ID = UUID("0d9e8f7a-6b5c-4d3e-8f2a-1b0c9d8e7f6a")
UNAUTHENTICATED_HEADER = "PolicyEngine-Unauthenticated-User"


class FakeDecoder:
    def __init__(self, claims: Mapping[str, Any] | Exception) -> None:
        self.claims = claims
        self.tokens: list[str] = []

    def decode(self, token: str) -> Mapping[str, Any]:
        self.tokens.append(token)
        if isinstance(self.claims, Exception):
            raise self.claims
        return self.claims


@pytest.fixture
def configured_auth(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(user_auth.PUBLIC_API_AUTH_REQUIRED_ENV, "1")
    monkeypatch.setenv(user_auth.PUBLIC_API_AUTH_ISSUER_ENV, ISSUER.rstrip("/"))
    monkeypatch.setenv(user_auth.PUBLIC_API_AUTH_AUDIENCE_ENV, AUDIENCE)

    def install(claims: Mapping[str, Any] | Exception) -> FakeDecoder:
        decoder = FakeDecoder(claims)
        monkeypatch.setattr(user_auth, "_decoder", lambda issuer, audience: decoder)
        return decoder

    return install


def _services() -> tuple[dict[str, RecordingService], dict[str, Any]]:
    services = {
        name: RecordingService()
        for name in ("account", "policy", "household", "simulation", "report")
    }
    factories = {
        "v2_account_service_factory": lambda: services["account"],
        "v2_user_policy_service_factory": lambda: services["policy"],
        "v2_user_household_service_factory": lambda: services["household"],
        "v2_user_simulation_service_factory": lambda: services["simulation"],
        "v2_user_report_service_factory": lambda: services["report"],
    }
    return services, factories


def _user_operations() -> list[tuple[str, str]]:
    """Every signed-in operation, read from the built application's OpenAPI."""

    _services_by_name, factories = _services()
    client, _flask_calls = user_route_client(require_user=None, **factories)
    paths = client.get("/v2/openapi.json").json()["paths"]
    operations = sorted(
        (method.upper(), path.replace("{association_id}", ASSOCIATION_ID))
        for path, methods in paths.items()
        if path.startswith(("/v2/me", "/v2/user-"))
        for method in methods
        if method in {"get", "post", "patch", "delete"}
    )
    # 5 account operations plus 5 for each of the 4 association resources.
    assert len(operations) >= 25
    return operations


@pytest.mark.parametrize(("method", "path"), _user_operations())
def test_every_user_route_fails_closed_without_a_token(method: str, path: str) -> None:
    services, factories = _services()
    client, flask_calls = user_route_client(require_user=None, **factories)

    response = client.request(
        method,
        f"{path}?country_id=us",
        json={} if method in {"POST", "PATCH"} else None,
        headers={"Origin": "https://app.policyengine.org"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "status": "error",
        "message": "Authentication is required",
    }
    assert "www-authenticate" in {
        value.strip().lower()
        for value in response.headers["access-control-expose-headers"].split(",")
    }
    assert all(not service.calls for service in services.values())
    assert flask_calls["count"] == 0


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/v2/user-policies?country_id=zz&bogus=1&limit=0", None),
        ("GET", "/v2/me", None),
        ("POST", "/v2/user-reports?country_id=us", {"user_id": "spoofed"}),
        ("PATCH", "/v2/user-households/not-a-uuid?country_id=us", {}),
        ("POST", "/v2/user-policies?country_id=uk", {"country_id": "us"}),
    ],
)
def test_authentication_precedes_query_body_and_path_validation(
    method: str, path: str, body: dict | None
) -> None:
    _services_by_name, factories = _services()
    client, _flask_calls = user_route_client(require_user=None, **factories)

    response = client.request(method, path, json=body)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_invalid_tokens_are_rejected_with_an_invalid_token_challenge(
    configured_auth,
) -> None:
    import jwt

    decoder = configured_auth(jwt.ExpiredSignatureError("expired"))
    _services_by_name, factories = _services()
    client, _flask_calls = user_route_client(require_user=None, **factories)

    response = client.get(
        "/v2/me?country_id=us",
        headers={"Authorization": "Bearer expired-token"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert "expired-token" not in response.text
    assert decoder.tokens == ["expired-token"]


def test_machine_client_principals_are_forbidden(configured_auth) -> None:
    configured_auth(
        {"iss": ISSUER, "sub": "abc123@clients", "gty": "client-credentials"}
    )
    services, factories = _services()
    client, _flask_calls = user_route_client(require_user=None, **factories)

    response = client.get(
        "/v2/user-policies?country_id=us",
        headers={"Authorization": "Bearer machine-token"},
    )

    assert response.status_code == 403
    assert response.json()["status"] == "error"
    assert not services["policy"].calls


def test_valid_user_tokens_reach_the_service_as_principals(configured_auth) -> None:
    configured_auth(
        {
            "iss": ISSUER,
            "sub": "google-oauth2|42",
            "email": "ada@example.com",
            "email_verified": True,
        }
    )
    services, factories = _services()
    services["policy"].next_result = None
    client, _flask_calls = user_route_client(require_user=None, **factories)

    response = client.delete(
        "/v2/user-policies/00000000-0000-0000-0000-000000000001?country_id=us",
        headers={"Authorization": "Bearer user-token"},
    )

    assert response.status_code == 204
    assert services["policy"].calls[0][1]["principal"] == UserPrincipal(
        issuer=ISSUER,
        subject="google-oauth2|42",
        email="ada@example.com",
    )


def test_unconfigured_authentication_is_unavailable_not_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in user_auth.PUBLIC_API_AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    services, factories = _services()
    client, _flask_calls = user_route_client(require_user=None, **factories)

    response = client.get(
        "/v2/me?country_id=us",
        headers={"Authorization": "Bearer user-token"},
    )

    assert response.status_code == 503
    assert not services["account"].calls


def test_default_dependencies_publish_the_bearer_security_scheme() -> None:
    _services_by_name, factories = _services()
    client, _flask_calls = user_route_client(require_user=None, **factories)

    schema = client.get("/v2/openapi.json").json()

    security_schemes = schema["components"]["securitySchemes"]
    assert "UserAccessToken" in security_schemes
    assert security_schemes["UnauthenticatedUser"] == {
        "type": "apiKey",
        "in": "header",
        "name": UNAUTHENTICATED_HEADER,
        "description": security_schemes["UnauthenticatedUser"]["description"],
    }
    for path in ("/v2/me", "/v2/user-policies", "/v2/user-reports"):
        # Separate requirement objects are alternatives in OpenAPI.
        assert schema["paths"][path]["get"]["security"] == [
            {"UserAccessToken": []},
            {"UnauthenticatedUser": []},
        ]
    assert "security" not in schema["paths"]["/v2/policies"]["get"]
    upgrade_header = next(
        parameter
        for parameter in schema["paths"]["/v2/me/upgrade"]["post"]["parameters"]
        if parameter["in"] == "header"
    )
    assert upgrade_header["name"] == UNAUTHENTICATED_HEADER
    assert upgrade_header["required"] is True


def _recorded_failure_logs(operation) -> tuple[object, list]:
    import logging

    from policyengine_api.fastapi_routes.v2 import user_resources

    class RecordingHandler(logging.Handler):
        def __init__(self) -> None:
            super().__init__(level=logging.ERROR)
            self.records: list[logging.LogRecord] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.records.append(record)

    # Alembic tests run logging.config.fileConfig, which disables loggers that
    # already exist, so re-enable this one and record on it directly.
    handler = RecordingHandler()
    was_disabled = user_resources.logger.disabled
    user_resources.logger.disabled = False
    user_resources.logger.addHandler(handler)
    try:
        response = user_resources.user_resource_operation(operation)
    finally:
        user_resources.logger.removeHandler(handler)
        user_resources.logger.disabled = was_disabled
    return response, handler.records


SECRET_SUBJECT = "|".join(("google-oauth2", "secret-subject"))


def test_unexpected_failures_are_logged_without_their_message() -> None:
    def fail():
        raise RuntimeError(f"{SECRET_SUBJECT} leaked into a message")

    response, records = _recorded_failure_logs(fail)

    assert response.status_code == 500
    (record,) = records
    assert record.getMessage() == "v2_user_operation_failed"
    attributes = record.policyengine_attributes
    assert attributes["error_type"] == "RuntimeError"
    assert "in fail" in attributes["error_frames"]
    assert "secret-subject" not in str(attributes)
    assert record.exc_info is None


def test_persistence_failures_are_logged_without_their_message() -> None:
    from sqlalchemy.exc import DataError

    def fail_in_database():
        raise DataError(
            "INSERT ...", {"subject": SECRET_SUBJECT}, Exception("bad value")
        )

    response, records = _recorded_failure_logs(fail_in_database)

    assert response.status_code == 503
    (record,) = records
    assert record.getMessage() == "v2_user_persistence_unavailable"
    attributes = record.policyengine_attributes
    assert attributes["error_type"] == "DataError"
    assert "in fail_in_database" in attributes["error_frames"]
    assert "secret-subject" not in str(attributes)


def _without_auth_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in user_auth.PUBLIC_API_AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("auth_configured", [False, True])
def test_the_unauthenticated_user_header_authenticates_a_signed_out_browser(
    monkeypatch: pytest.MonkeyPatch, configured_auth, auth_configured: bool
) -> None:
    if not auth_configured:
        _without_auth_settings(monkeypatch)
    services, factories = _services()
    services["policy"].next_result = UserPolicyPage(
        items=(), offset=0, limit=100, has_more=False
    )
    client, _flask_calls = user_route_client(require_user=None, **factories)

    response = client.get(
        "/v2/user-policies?country_id=us",
        headers={UNAUTHENTICATED_HEADER: str(BROWSER_USER_ID)},
    )

    assert response.status_code == 200
    assert services["policy"].calls[0][1]["principal"] == UnauthenticatedPrincipal(
        user_id=BROWSER_USER_ID
    )


@pytest.mark.parametrize(
    "header_value",
    [
        "not-a-uuid",
        str(BROWSER_USER_ID).upper(),
        BROWSER_USER_ID.hex,
        f"urn:uuid:{BROWSER_USER_ID}",
        f"{BROWSER_USER_ID} ",
    ],
)
def test_malformed_unauthenticated_user_headers_are_unauthenticated(
    header_value: str,
) -> None:
    services, factories = _services()
    client, _flask_calls = user_route_client(require_user=None, **factories)

    response = client.post(
        "/v2/user-reports?country_id=zz",
        headers={UNAUTHENTICATED_HEADER: header_value},
        json={"bogus": True},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "status": "error",
        "message": f"The {UNAUTHENTICATED_HEADER} header must be a canonical UUID",
    }
    assert all(not service.calls for service in services.values())


def test_a_bearer_token_takes_precedence_over_the_unauthenticated_header(
    configured_auth,
) -> None:
    configured_auth({"iss": ISSUER, "sub": "google-oauth2|42"})
    services, factories = _services()
    services["account"].next_result = AccountExport(
        user=None, policies=(), households=(), simulations=(), reports=()
    )
    client, _flask_calls = user_route_client(require_user=None, **factories)

    response = client.get(
        "/v2/me/export?country_id=us",
        headers={
            "Authorization": "Bearer user-token",
            UNAUTHENTICATED_HEADER: str(BROWSER_USER_ID),
        },
    )

    assert response.status_code == 200
    assert services["account"].calls[0][1]["principal"] == UserPrincipal(
        issuer=ISSUER, subject="google-oauth2|42"
    )


def test_an_invalid_bearer_token_never_falls_back_to_the_header(
    configured_auth,
) -> None:
    import jwt

    configured_auth(jwt.InvalidSignatureError("bad signature"))
    services, factories = _services()
    client, _flask_calls = user_route_client(require_user=None, **factories)

    response = client.get(
        "/v2/user-policies?country_id=us",
        headers={
            "Authorization": "Bearer forged-token",
            UNAUTHENTICATED_HEADER: str(BROWSER_USER_ID),
        },
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert not services["policy"].calls


def test_machine_client_principals_are_forbidden_beside_the_header(
    configured_auth,
) -> None:
    configured_auth(
        {"iss": ISSUER, "sub": "abc123@clients", "gty": "client-credentials"}
    )
    services, factories = _services()
    client, _flask_calls = user_route_client(require_user=None, **factories)

    response = client.get(
        "/v2/user-policies?country_id=us",
        headers={
            "Authorization": "Bearer machine-token",
            UNAUTHENTICATED_HEADER: str(BROWSER_USER_ID),
        },
    )

    assert response.status_code == 403
    assert not services["policy"].calls


def test_a_bearer_token_without_auth_settings_is_unavailable_beside_the_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _without_auth_settings(monkeypatch)
    services, factories = _services()
    client, _flask_calls = user_route_client(require_user=None, **factories)

    response = client.get(
        "/v2/me?country_id=us",
        headers={
            "Authorization": "Bearer user-token",
            UNAUTHENTICATED_HEADER: str(BROWSER_USER_ID),
        },
    )

    assert response.status_code == 503
    assert not services["account"].calls


def test_upgrade_with_only_the_unauthenticated_header_requires_sign_in() -> None:
    services, factories = _services()
    client, _flask_calls = user_route_client(require_user=None, **factories)

    response = client.post(
        "/v2/me/upgrade?country_id=us",
        headers={UNAUTHENTICATED_HEADER: str(BROWSER_USER_ID)},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert not services["account"].calls


def test_browsers_may_send_the_unauthenticated_header_cross_origin() -> None:
    _services_by_name, factories = _services()
    client, _flask_calls = user_route_client(require_user=None, **factories)

    response = client.options(
        "/v2/user-policies?country_id=us",
        headers={
            "Origin": "https://app.policyengine.org",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": (
                f"content-type,{UNAUTHENTICATED_HEADER.lower()}"
            ),
        },
    )

    assert response.status_code == 200
    allowed = {
        value.strip().lower()
        for value in response.headers["access-control-allow-headers"].split(",")
    }
    assert UNAUTHENTICATED_HEADER.lower() in allowed
