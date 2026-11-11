"""The deployed-API tests' headers, and the Public API's answer to them.

``tests/integration/deployed_api_credentials.py`` builds the headers the tests
under ``tests/integration`` send to a deployed Public API: the CI server token
in ``Authorization: Bearer``, and a signed-in user's token forwarded in
``PolicyEngine-User-Authorization``. The requests here go through the ASGI
application production serves, with real RS256 tokens, with the enforcement
setting off and on, so the deployed tests' expectations hold in both until
staging switches it on.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from policyengine_api.services.v2.identity.types import UserPrincipal
from policyengine_api.services.v2.user_policies.types import UserPolicyPage
from tests.integration.deployed_api_credentials import (
    CI_SERVER_ACCESS_TOKEN_ENV,
    FORWARDED_USER_AUTHORIZATION_HEADER,
    MissingServerCredentialError,
    forwarded_user_headers,
    server_credential_headers,
)
from tests.unit.cloud_run_deploy_support import REPO
from tests.unit.credential_token_support import (
    ISSUER,
    USER_SUBJECT,
    bearer,
    configure_credentials,
    server_token,
    user_token,
)
from tests.unit.v2.user_route_support import RecordingService, user_route_client

ENFORCEMENT_ENV = "PUBLIC_API_SERVER_CREDENTIAL_REQUIRED"
USER_POLICIES_PATH = "/v2/user-policies?country_id=us"
REFUSAL = {"status": "error", "message": "Authentication is required"}


@pytest.fixture(params=["", "1"], ids=["enforcement-off", "enforcement-on"])
def enforcement(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    configure_credentials(monkeypatch)
    monkeypatch.setenv(ENFORCEMENT_ENV, request.param)
    return request.param


def _ci_server_headers() -> dict[str, str]:
    """Return the headers a CI job sends, with a listed client's token."""
    return server_credential_headers({CI_SERVER_ACCESS_TOKEN_ENV: server_token()})


def _empty_policy_page(_name: str, _kwargs: dict) -> UserPolicyPage:
    return UserPolicyPage(items=(), offset=0, limit=100, has_more=False)


def test_sends_the_ci_token_as_a_bearer_credential() -> None:
    headers = server_credential_headers(
        {CI_SERVER_ACCESS_TOKEN_ENV: "header.payload.signature"}
    )

    assert headers == {"Authorization": "Bearer header.payload.signature"}


@pytest.mark.parametrize("token", [None, "", " \t"], ids=["unset", "empty", "blank"])
def test_fails_with_a_clear_message_without_the_token(token: str | None) -> None:
    environ = {} if token is None else {CI_SERVER_ACCESS_TOKEN_ENV: token}

    with pytest.raises(MissingServerCredentialError) as refusal:
        server_credential_headers(environ)

    assert CI_SERVER_ACCESS_TOKEN_ENV in str(refusal.value)
    assert "request_ci_server_token.sh" in str(refusal.value)


def test_forwards_a_signed_in_users_token_beside_the_server_credential() -> None:
    assert forwarded_user_headers("user.token.value") == {
        "PolicyEngine-User-Authorization": "Bearer user.token.value"
    }
    assert FORWARDED_USER_AUTHORIZATION_HEADER.lower() != "authorization"


def test_the_ci_credential_is_served_on_any_route(enforcement: str) -> None:
    del enforcement
    client, flask_calls = user_route_client(require_user=None)

    response = client.get("/us/metadata", headers=_ci_server_headers())

    assert response.status_code == 200
    assert flask_calls["count"] == 1


def test_a_request_without_the_credential_is_refused_once_enforcement_is_on(
    enforcement: str,
) -> None:
    client, flask_calls = user_route_client(require_user=None)

    response = client.get("/us/metadata")

    if enforcement:
        assert response.status_code == 401
        assert response.json() == REFUSAL
        assert flask_calls["count"] == 0
    else:
        assert response.status_code == 200


def test_a_forwarded_user_is_authenticated_beside_the_ci_credential(
    enforcement: str,
) -> None:
    del enforcement
    service = RecordingService(_empty_policy_page)
    client, _flask_calls = user_route_client(
        require_user=None, v2_user_policy_service_factory=lambda: service
    )

    response = client.get(
        USER_POLICIES_PATH,
        headers={**_ci_server_headers(), **forwarded_user_headers(user_token())},
    )

    assert response.status_code == 200
    ((_method, arguments),) = service.calls
    assert arguments["principal"] == UserPrincipal(issuer=ISSUER, subject=USER_SUBJECT)


@pytest.mark.parametrize(
    "with_ci_credential", [True, False], ids=["ci-credential", "no-credential"]
)
def test_user_routes_refuse_a_request_without_a_user(
    enforcement: str, *, with_ci_credential: bool
) -> None:
    # The deployed fail-closed checks send both: 401 with a Bearer challenge
    # either way, whether or not enforcement is on.
    del enforcement
    service = RecordingService(_empty_policy_page)
    client, _flask_calls = user_route_client(
        require_user=None, v2_user_policy_service_factory=lambda: service
    )
    headers = _ci_server_headers() if with_ci_credential else {}

    response = client.get(USER_POLICIES_PATH, headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert response.json()["status"] == "error"
    assert service.calls == []


def test_a_users_token_alone_in_authorization_is_refused_once_enforcement_is_on(
    enforcement: str,
) -> None:
    # Why the deployed tests forward the user's token instead of sending it in
    # Authorization: once enforcement is on, only a server credential is served.
    service = RecordingService(_empty_policy_page)
    client, _flask_calls = user_route_client(
        require_user=None, v2_user_policy_service_factory=lambda: service
    )

    response = client.get(
        USER_POLICIES_PATH, headers={"Authorization": bearer(user_token())}
    )

    if enforcement:
        assert response.status_code == 401
        assert response.json() == REFUSAL
        assert service.calls == []
    else:
        assert response.status_code == 200


def test_a_deployed_test_fails_instead_of_skipping_without_the_token() -> None:
    # A deployed test run without CI_SERVER_ACCESS_TOKEN errors before any
    # request: port 9 (discard) is never called.
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", ""),
        "API_BASE_URL": "http://127.0.0.1:9",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "tests/integration/test_cloud_run_candidate.py"
            "::test_cloud_run_candidate_health_routes",
        ],
        cwd=REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1, result.stdout
    assert "1 error" in result.stdout
    assert "skipped" not in result.stdout
    assert CI_SERVER_ACCESS_TOKEN_ENV in result.stdout
    assert "ConnectError" not in result.stdout
