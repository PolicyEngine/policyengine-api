"""Unit tests for :mod:`policyengine_api.libs.auth0_management`."""

from __future__ import annotations

import httpx
import pytest

from policyengine_api.libs.auth0_management import (
    Auth0ManagementClient,
    Auth0ManagementConfigurationError,
    Auth0ManagementError,
    Auth0ManagementSettings,
    build_auth0_user_deleter,
    load_auth0_management_settings,
)


DOMAIN = "policyengine.us.auth0.com"
SECRET_RESOURCE = "projects/p/secrets/auth0-management/versions/latest"


def _client(handler, **settings) -> tuple[Auth0ManagementClient, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    values = {"domain": DOMAIN, "client_id": "m2m", "client_secret": "raw-secret"}
    values.update(settings)
    return (
        Auth0ManagementClient(
            Auth0ManagementSettings(**values),
            http_client=httpx.Client(transport=httpx.MockTransport(record)),
            secret_loader=lambda resource: "loaded-secret",
        ),
        requests,
    )


def _token_then(status: int):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(
                200, json={"access_token": "mgmt", "expires_in": 3600}
            )
        return httpx.Response(status)

    return handler


def test_settings_are_optional_and_all_or_none() -> None:
    assert load_auth0_management_settings({}) is None
    assert build_auth0_user_deleter({}) is None
    with pytest.raises(Auth0ManagementConfigurationError, match="partially"):
        load_auth0_management_settings({"AUTH0_MANAGEMENT_DOMAIN": DOMAIN})
    with pytest.raises(Auth0ManagementConfigurationError, match="exactly one"):
        load_auth0_management_settings(
            {
                "AUTH0_MANAGEMENT_DOMAIN": DOMAIN,
                "AUTH0_MANAGEMENT_CLIENT_ID": "m2m",
                "AUTH0_MANAGEMENT_CLIENT_SECRET": "raw",
                "AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE": SECRET_RESOURCE,
            }
        )
    with pytest.raises(Auth0ManagementConfigurationError, match="bare host"):
        load_auth0_management_settings(
            {
                "AUTH0_MANAGEMENT_DOMAIN": f"https://{DOMAIN}/",
                "AUTH0_MANAGEMENT_CLIENT_ID": "m2m",
                "AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE": SECRET_RESOURCE,
            }
        )
    settings = load_auth0_management_settings(
        {
            "AUTH0_MANAGEMENT_DOMAIN": DOMAIN,
            "AUTH0_MANAGEMENT_CLIENT_ID": "m2m",
            "AUTH0_MANAGEMENT_CLIENT_SECRET_RESOURCE": SECRET_RESOURCE,
        }
    )
    assert settings is not None
    assert "raw" not in repr(settings)


@pytest.mark.parametrize("status", [204, 404])
def test_delete_user_uses_an_encoded_subject_and_tolerates_absent_users(
    status: int,
) -> None:
    client, requests = _client(_token_then(status))

    client.delete_user("google-oauth2|1234")

    token_request, delete_request = requests
    assert token_request.url == f"https://{DOMAIN}/oauth/token"
    assert b'"audience":"https://policyengine.us.auth0.com/api/v2/"' in (
        token_request.content.replace(b" ", b"")
    )
    assert delete_request.method == "DELETE"
    assert delete_request.url.raw_path == b"/api/v2/users/google-oauth2%7C1234"
    assert delete_request.headers["authorization"] == "Bearer mgmt"


def test_token_is_cached_and_secret_resources_are_loaded() -> None:
    client, requests = _client(
        _token_then(204), client_secret="", client_secret_resource=SECRET_RESOURCE
    )

    client.delete_user("auth0|1")
    client.delete_user("auth0|2")

    assert [request.url.raw_path for request in requests] == [
        b"/oauth/token",
        b"/api/v2/users/auth0%7C1",
        b"/api/v2/users/auth0%7C2",
    ]
    assert b"loaded-secret" in requests[0].content


@pytest.mark.parametrize("status", [401, 403, 500])
def test_failed_deletions_raise_without_leaking_subjects(status: int) -> None:
    client, _requests = _client(_token_then(status))

    with pytest.raises(Auth0ManagementError) as error:
        client.delete_user("google-oauth2|secret-subject")

    assert "secret-subject" not in str(error.value)
