"""Native FastAPI contract tests for admins' email invitation routes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from policyengine_api.data.v2.models import UserType
from policyengine_api.services.v2.user_invitations.types import (
    AdminInvitationPage,
    AdminInvitationRead,
    AdminInvitationSearch,
)
from policyengine_api.services.v2.user_invitations.validators import (
    InvitationNotFoundError,
)
from policyengine_api.services.v2.user_types.validators import (
    UserTypeBelowMinimumError,
)
from tests.unit.v2.user_route_support import (
    CREATED_AT,
    OWNER_ID,
    PRINCIPAL,
    RecordingService,
    signed_out_browser,
    user_route_client,
)

INVITATION_ID = UUID("00000000-0000-0000-0000-000000000091")
EXPIRES_AT = datetime(2026, 1, 8, tzinfo=UTC)


def _invitation(**changes) -> AdminInvitationRead:
    values = {
        "id": INVITATION_ID,
        "email": "Ada@Example.org",
        "user_type": UserType.AUTHOR,
        "invited_by_user_id": OWNER_ID,
        "created_at": CREATED_AT,
        "expires_at": EXPIRES_AT,
        "expired": False,
        "last_sent_at": None,
        "last_send_error": "postmark_406",
    }
    values.update(changes)
    return AdminInvitationRead(**values)


EXPECTED_INVITATION = {
    "id": str(INVITATION_ID),
    "email": "Ada@Example.org",
    "user_type": "author",
    "invited_by_user_id": str(OWNER_ID),
    "created_at": "2026-01-01T00:00:00Z",
    "expires_at": "2026-01-08T00:00:00Z",
    "expired": False,
    "last_sent_at": None,
    "last_send_error": "postmark_406",
}


def _result(name: str, kwargs: dict):
    if name == "list_invitations":
        search = kwargs["search"]
        return AdminInvitationPage(
            items=(_invitation(),),
            offset=search.offset,
            limit=search.limit,
            has_more=False,
        )
    if name == "revoke_invitation":
        return None
    return _invitation()


def _client(
    invitations: RecordingService | None = None,
    user_types: RecordingService | None = None,
    **client_options,
):
    invitations = invitations or RecordingService(_result)
    user_types = user_types or RecordingService(UserType.ADMIN)
    client, _flask_calls = user_route_client(
        v2_user_invitation_service_factory=lambda: invitations,
        v2_user_type_service_factory=lambda: user_types,
        **client_options,
    )
    return client, invitations, user_types


def test_admins_invite_an_address_to_become_an_author_or_admin() -> None:
    client, invitations, user_types = _client()

    response = client.post(
        "/v2/admin/invitations",
        json={"email": "  Ada@Example.org ", "user_type": "author"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {"item": EXPECTED_INVITATION},
    }
    assert user_types.calls == [
        (
            "require_minimum_user_type",
            {"principal": PRINCIPAL, "minimum": UserType.ADMIN},
        )
    ]
    assert invitations.calls == [
        (
            "create_invitation",
            {
                "principal": PRINCIPAL,
                "email": "Ada@Example.org",
                "user_type": UserType.AUTHOR,
            },
        )
    ]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"email": "ada@example.org"},
        {"email": "ada@example.org", "user_type": "standard"},
        {"email": "ada@example.org", "user_type": "unauthenticated"},
        {"email": "ada", "user_type": "author"},
        {"email": "ada@@example.org", "user_type": "author"},
        {"email": "ada smith@example.org", "user_type": "author"},
        {"email": "<ada@example.org>", "user_type": "author"},
        {"email": "a@" + "b" * 319, "user_type": "author"},
        {"email": "ada@example.org", "user_type": "author", "note": "hi"},
    ],
)
def test_an_invitation_needs_one_address_and_an_author_or_admin_type(
    body: dict,
) -> None:
    client, invitations, _user_types = _client()

    response = client.post("/v2/admin/invitations", json=body)

    assert response.status_code == 422
    assert invitations.calls == []


def test_admins_list_open_invitations_a_page_at_a_time() -> None:
    client, invitations, _user_types = _client()

    response = client.get("/v2/admin/invitations?offset=2&limit=5")
    default = client.get("/v2/admin/invitations")

    assert response.status_code == 200
    assert response.json()["result"] == {
        "items": [EXPECTED_INVITATION],
        "offset": 2,
        "limit": 5,
        "has_more": False,
    }
    assert default.status_code == 200
    assert [kwargs for name, kwargs in invitations.calls] == [
        {"principal": PRINCIPAL, "search": AdminInvitationSearch(offset=2, limit=5)},
        {"principal": PRINCIPAL, "search": AdminInvitationSearch(offset=0, limit=100)},
    ]


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=501", "offset=-1", "unknown=1", "limit=1&limit=2"]
)
def test_the_invitation_list_refuses_invalid_queries(query: str) -> None:
    client, invitations, _user_types = _client()

    response = client.get(f"/v2/admin/invitations?{query}")

    assert response.status_code == 422
    assert invitations.calls == []


def test_admins_resend_and_revoke_an_invitation() -> None:
    client, invitations, _user_types = _client()

    resent = client.post(f"/v2/admin/invitations/{INVITATION_ID}/resend")
    revoked = client.delete(f"/v2/admin/invitations/{INVITATION_ID}")

    assert resent.status_code == 200
    assert resent.json()["result"] == {"item": EXPECTED_INVITATION}
    assert revoked.status_code == 204
    assert revoked.content == b""
    assert invitations.calls == [
        ("resend_invitation", {"principal": PRINCIPAL, "invitation_id": INVITATION_ID}),
        ("revoke_invitation", {"principal": PRINCIPAL, "invitation_id": INVITATION_ID}),
    ]


def test_an_invitation_that_isnt_open_is_not_found() -> None:
    invitations = RecordingService(_result)
    invitations.error = InvitationNotFoundError("No pending invitation has this ID")
    client, _invitations, _user_types = _client(invitations)

    responses = [
        client.post(f"/v2/admin/invitations/{INVITATION_ID}/resend"),
        client.delete(f"/v2/admin/invitations/{INVITATION_ID}"),
    ]

    assert [response.status_code for response in responses] == [404, 404]
    assert responses[0].json() == {
        "status": "error",
        "message": "No pending invitation has this ID",
    }


def test_callers_below_admin_reach_no_invitation_route() -> None:
    user_types = RecordingService()
    user_types.error = UserTypeBelowMinimumError("Only admins may do this")
    client, invitations, _user_types = _client(user_types=user_types)

    responses = [
        client.post(
            "/v2/admin/invitations",
            json={"email": "ada@example.org", "user_type": "admin"},
        ),
        client.get("/v2/admin/invitations"),
        client.post(f"/v2/admin/invitations/{INVITATION_ID}/resend"),
        client.delete(f"/v2/admin/invitations/{INVITATION_ID}"),
    ]

    assert [response.status_code for response in responses] == [403] * 4
    assert invitations.calls == []


def test_a_service_refusal_inside_the_transaction_is_403() -> None:
    invitations = RecordingService(_result)
    invitations.error = UserTypeBelowMinimumError("Only admins may do this")
    client, _invitations, _user_types = _client(invitations)

    response = client.get("/v2/admin/invitations")

    assert response.status_code == 403


def test_signed_out_browsers_reach_no_invitation_route() -> None:
    user_types = RecordingService()
    user_types.error = UserTypeBelowMinimumError("Only admins may do this")
    client, invitations, _user_types = _client(
        user_types=user_types, require_user=signed_out_browser
    )

    response = client.get("/v2/admin/invitations")

    assert response.status_code == 403
    assert invitations.calls == []


def test_invitation_routes_need_a_credential() -> None:
    client, invitations, _user_types = _client(require_user=None)

    response = client.get("/v2/admin/invitations")

    assert response.status_code == 401
    assert invitations.calls == []


def test_the_openapi_document_describes_the_invitation_routes() -> None:
    client, _invitations, _user_types = _client()

    paths = client.get("/v2/openapi.json").json()["paths"]

    create = paths["/v2/admin/invitations"]["post"]
    assert set(create["responses"]) >= {"201", "401", "403", "413", "422", "503"}
    assert set(
        paths["/v2/admin/invitations/{invitation_id}"]["delete"]["responses"]
    ) >= {
        "204",
        "404",
    }
    assert (
        "404"
        in paths["/v2/admin/invitations/{invitation_id}/resend"]["post"]["responses"]
    )
