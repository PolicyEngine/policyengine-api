"""Router-level authentication for every signed-in user route."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from policyengine_api.libs import user_auth
from policyengine_api.services.v2.identity.types import UserPrincipal
from tests.unit.v2.user_route_support import RecordingService, user_route_client


ISSUER = "https://auth.example.test/"
AUDIENCE = "https://api.policyengine.org/"
USER_ROUTE_REQUESTS = (
    ("GET", "/v2/me?country_id=us", None),
    ("PATCH", "/v2/me?country_id=us", {"first_name": "Ada"}),
    ("DELETE", "/v2/me?country_id=us", None),
    ("GET", "/v2/me/export?country_id=us", None),
    ("POST", "/v2/me/imports?country_id=us", {}),
    ("GET", "/v2/user-policies?country_id=us", None),
    ("POST", "/v2/user-policies?country_id=us", {"country_id": "us"}),
    ("GET", "/v2/user-households?country_id=us", None),
    ("GET", "/v2/user-simulations?country_id=us", None),
    ("GET", "/v2/user-reports?country_id=us", None),
    (
        "DELETE",
        "/v2/user-reports/00000000-0000-0000-0000-000000000001?country_id=us",
        None,
    ),
)


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


@pytest.mark.parametrize(("method", "path", "body"), USER_ROUTE_REQUESTS)
def test_every_user_route_fails_closed_without_a_token(
    method: str, path: str, body: dict | None
) -> None:
    services, factories = _services()
    client, flask_calls = user_route_client(require_user=None, **factories)

    response = client.request(
        method,
        path,
        json=body,
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

    assert "UserAccessToken" in schema["components"]["securitySchemes"]
    for path in ("/v2/me", "/v2/user-policies", "/v2/user-reports"):
        assert {"UserAccessToken": []} in schema["paths"][path]["get"]["security"]
    assert "security" not in schema["paths"]["/v2/policies"]["get"]
