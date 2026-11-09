"""A credentialed server can act for a user on the signed-in user routes.

The server sends its own client-credentials token in ``Authorization`` and the
user it acts for in ``PolicyEngine-User-Authorization: Bearer <token>`` (a
signed-in user) or ``PolicyEngine-Unauthenticated-User`` (a signed-out
browser). The user routes then authenticate that user exactly as they would
a direct request carrying the same credential. Without a server credential,
``PolicyEngine-User-Authorization`` is ignored and a direct request works as
before. Every request uses real RS256 tokens through the ASGI application.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from policyengine_api.services.v2.identity.types import (
    AccountConversionOutcome,
    UnauthenticatedPrincipal,
    UserPrincipal,
)
from policyengine_api.services.v2.user_accounts.types import (
    AccountRead,
    AccountUpgrade,
)
from policyengine_api.services.v2.user_policies.types import UserPolicyPage
from tests.unit.credential_token_support import (
    EXPIRED,
    ISSUER,
    OTHER_SIGNING_KEY,
    USER_SUBJECT,
    bearer,
    configure_credentials,
    server_token,
    user_token,
)
from tests.unit.v2.user_route_support import RecordingService, user_route_client

FORWARDED_USER_HEADER = "PolicyEngine-User-Authorization"
UNAUTHENTICATED_HEADER = "PolicyEngine-Unauthenticated-User"
BROWSER_USER_ID = UUID("3c9d5e7f-1a2b-4c6d-8e0f-a1b2c3d4e5f6")
OTHER_USER_SUBJECT = "auth0|other-user-0001"
USER_POLICIES_PATH = "/v2/user-policies?country_id=us"
SIGNED_IN_USER = UserPrincipal(issuer=ISSUER, subject=USER_SUBJECT)
SERVER_AUTHORIZATION = {"Authorization": bearer(server_token())}


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_credentials(monkeypatch)


def _empty_policy_page(_name: str, _kwargs: dict) -> UserPolicyPage:
    return UserPolicyPage(items=(), offset=0, limit=100, has_more=False)


def _policy_client():
    service = RecordingService(_empty_policy_page)
    client, _flask_calls = user_route_client(
        require_user=None, v2_user_policy_service_factory=lambda: service
    )
    return client, service


def _principal(service: RecordingService) -> object:
    ((_method, arguments),) = service.calls
    return arguments["principal"]


def test_a_server_can_forward_a_signed_in_users_token() -> None:
    client, service = _policy_client()

    response = client.get(
        USER_POLICIES_PATH,
        headers={
            **SERVER_AUTHORIZATION,
            FORWARDED_USER_HEADER: bearer(user_token()),
        },
    )

    assert response.status_code == 200
    assert _principal(service) == SIGNED_IN_USER


def test_a_server_can_forward_a_signed_out_browsers_user() -> None:
    client, service = _policy_client()

    response = client.get(
        USER_POLICIES_PATH,
        headers={**SERVER_AUTHORIZATION, UNAUTHENTICATED_HEADER: str(BROWSER_USER_ID)},
    )

    assert response.status_code == 200
    assert _principal(service) == UnauthenticatedPrincipal(user_id=BROWSER_USER_ID)


def test_a_forwarded_users_token_takes_precedence_over_the_browsers_user() -> None:
    client, service = _policy_client()

    response = client.get(
        USER_POLICIES_PATH,
        headers={
            **SERVER_AUTHORIZATION,
            FORWARDED_USER_HEADER: bearer(user_token()),
            UNAUTHENTICATED_HEADER: str(BROWSER_USER_ID),
        },
    )

    assert response.status_code == 200
    assert _principal(service) == SIGNED_IN_USER


def test_a_server_that_forwards_no_user_must_authenticate_one() -> None:
    client, service = _policy_client()

    response = client.get(USER_POLICIES_PATH, headers=SERVER_AUTHORIZATION)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "status": "error",
        "message": "Authentication is required",
    }
    assert service.calls == []


@pytest.mark.parametrize(
    "forwarded_token",
    [
        user_token(exp=EXPIRED),
        user_token(signing_key=OTHER_SIGNING_KEY),
        "not-a-jwt",
    ],
    ids=["expired", "another-signing-key", "malformed"],
)
def test_an_invalid_forwarded_token_is_refused_as_a_direct_one_was(
    forwarded_token: str,
) -> None:
    client, service = _policy_client()

    response = client.get(
        USER_POLICIES_PATH,
        headers={
            **SERVER_AUTHORIZATION,
            FORWARDED_USER_HEADER: bearer(forwarded_token),
            UNAUTHENTICATED_HEADER: str(BROWSER_USER_ID),
        },
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert response.json() == {
        "status": "error",
        "message": "The bearer access token is invalid",
    }
    assert service.calls == []


def test_a_forwarded_machine_token_is_forbidden() -> None:
    client, service = _policy_client()

    response = client.get(
        USER_POLICIES_PATH,
        headers={
            **SERVER_AUTHORIZATION,
            FORWARDED_USER_HEADER: bearer(server_token()),
        },
    )

    assert response.status_code == 403
    assert service.calls == []


def test_a_forwarded_malformed_browser_user_is_refused() -> None:
    client, service = _policy_client()

    response = client.get(
        USER_POLICIES_PATH,
        headers={**SERVER_AUTHORIZATION, UNAUTHENTICATED_HEADER: "not-a-uuid"},
    )

    assert response.status_code == 401
    assert response.json()["message"] == (
        f"The {UNAUTHENTICATED_HEADER} header must be a canonical UUID"
    )
    assert service.calls == []


def test_two_forwarded_user_headers_are_refused() -> None:
    client, service = _policy_client()

    response = client.get(
        USER_POLICIES_PATH,
        headers=[
            ("Authorization", bearer(server_token())),
            (FORWARDED_USER_HEADER, bearer(user_token())),
            (FORWARDED_USER_HEADER, bearer(user_token(OTHER_USER_SUBJECT))),
        ],
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert service.calls == []


def test_a_blank_forwarded_header_counts_as_none() -> None:
    client, service = _policy_client()

    response = client.get(
        USER_POLICIES_PATH,
        headers={
            **SERVER_AUTHORIZATION,
            FORWARDED_USER_HEADER: " ",
            UNAUTHENTICATED_HEADER: str(BROWSER_USER_ID),
        },
    )

    assert response.status_code == 200
    assert _principal(service) == UnauthenticatedPrincipal(user_id=BROWSER_USER_ID)


def test_a_forwarded_credential_with_another_scheme_is_refused() -> None:
    client, service = _policy_client()

    response = client.get(
        USER_POLICIES_PATH,
        headers={
            **SERVER_AUTHORIZATION,
            FORWARDED_USER_HEADER: "Basic dXNlcjpwYXNzd29yZA==",
            UNAUTHENTICATED_HEADER: str(BROWSER_USER_ID),
        },
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert service.calls == []


def test_two_forwarded_headers_without_a_server_credential_are_ignored() -> None:
    client, service = _policy_client()

    response = client.get(
        USER_POLICIES_PATH,
        headers=[
            ("Authorization", bearer(user_token())),
            (FORWARDED_USER_HEADER, bearer(user_token(OTHER_USER_SUBJECT))),
            (FORWARDED_USER_HEADER, "Bearer made-up"),
        ],
    )

    assert response.status_code == 200
    assert _principal(service) == SIGNED_IN_USER


def test_a_server_can_upgrade_a_browsers_user_into_the_forwarded_account() -> None:
    account = AccountRead(
        id=UUID("00000000-0000-0000-0000-000000000071"),
        user_type="standard",
        primary_country="us",
        first_name=None,
        last_name=None,
        email=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    service = RecordingService(
        AccountUpgrade(account=account, outcome=AccountConversionOutcome.CONVERTED)
    )
    client, _flask_calls = user_route_client(
        require_user=None, v2_account_service_factory=lambda: service
    )

    response = client.post(
        "/v2/me/upgrade?country_id=us",
        headers={
            **SERVER_AUTHORIZATION,
            FORWARDED_USER_HEADER: bearer(user_token()),
            UNAUTHENTICATED_HEADER: str(BROWSER_USER_ID),
        },
    )

    assert response.status_code == 200
    assert service.calls == [
        (
            "upgrade_account",
            {
                "principal": SIGNED_IN_USER,
                "unauthenticated_user_id": BROWSER_USER_ID,
                "country_id": "us",
            },
        )
    ]


def test_a_direct_users_token_still_works_and_ignores_a_forwarded_one() -> None:
    client, service = _policy_client()

    response = client.get(
        USER_POLICIES_PATH,
        headers={
            "Authorization": bearer(user_token()),
            FORWARDED_USER_HEADER: bearer(user_token(OTHER_USER_SUBJECT)),
        },
    )

    assert response.status_code == 200
    assert _principal(service) == SIGNED_IN_USER


def test_a_forwarded_token_without_a_server_credential_is_ignored() -> None:
    client, service = _policy_client()

    response = client.get(
        USER_POLICIES_PATH,
        headers={FORWARDED_USER_HEADER: bearer(user_token())},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert service.calls == []
