"""Native FastAPI contract tests for admins' user routes and minimum types."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from policyengine_api.data.v2.models import UserType, UserTypeChangeSource
from policyengine_api.fastapi_routes.v2.errors_support import (
    V2PermissionDeniedError,
)
from policyengine_api.fastapi_routes.v2.user_type_support import (
    minimum_user_type_dependency,
)
from policyengine_api.services.v2.user_accounts.types import AccountDeletion
from policyengine_api.services.v2.user_accounts.validators import (
    AccountDeletionUnavailableError,
    AccountIdentityDeletionError,
)
from policyengine_api.services.v2.user_types.types import (
    AdminUserPage,
    AdminUserRead,
    AdminUserSearch,
    UserTypeChangeRead,
)
from policyengine_api.services.v2.user_types.validators import (
    LastAdminDeletionError,
    LastAdminDemotionError,
    SignedInUserNotFoundError,
    UserTypeBelowMinimumError,
    UserTypeChangedError,
    UserTypeCheckUnavailableError,
)
from tests.unit.v2.user_route_support import (
    CREATED_AT,
    OWNER_ID,
    PRINCIPAL,
    UNAUTHENTICATED_PRINCIPAL,
    RecordingService,
    signed_out_browser,
    user_route_client,
)

TARGET_ID = UUID("00000000-0000-0000-0000-000000000081")
CHANGE_ID = UUID("00000000-0000-0000-0000-000000000082")
LAST_SEEN_AT = datetime(2026, 2, 1, tzinfo=UTC)


def _user(**changes) -> AdminUserRead:
    values = {
        "id": TARGET_ID,
        "user_type": UserType.AUTHOR,
        "email": "bob@example.test",
        "first_name": "Bob",
        "last_name": None,
        "primary_country": "uk",
        "created_at": CREATED_AT,
        "last_seen_at": LAST_SEEN_AT,
    }
    values.update(changes)
    return AdminUserRead(**values)


def _change() -> UserTypeChangeRead:
    return UserTypeChangeRead(
        id=CHANGE_ID,
        user_id=TARGET_ID,
        previous_user_type=UserType.STANDARD,
        new_user_type=UserType.AUTHOR,
        changed_by_user_id=OWNER_ID,
        changed_by_email="alice@example.test",
        source=UserTypeChangeSource.ADMIN_ROUTE,
        created_at=LAST_SEEN_AT,
    )


def _result(name: str, kwargs: dict):
    if name == "require_minimum_user_type":
        return UserType.ADMIN
    if name == "list_users":
        search = kwargs["search"]
        return AdminUserPage(
            items=(_user(),), offset=search.offset, limit=search.limit, has_more=True
        )
    if name == "list_user_type_changes":
        return (_change(),)
    return _user()


def _client(service: RecordingService | None = None, **client_options):
    service = service or RecordingService(_result)
    client, _flask_calls = user_route_client(
        v2_user_type_service_factory=lambda: service, **client_options
    )
    return client, service


EXPECTED_USER = {
    "id": str(TARGET_ID),
    "user_type": "author",
    "email": "bob@example.test",
    "first_name": "Bob",
    "last_name": None,
    "primary_country": "uk",
    "created_at": "2026-01-01T00:00:00Z",
    "last_seen_at": "2026-02-01T00:00:00Z",
}


def test_admins_list_users_by_part_of_an_email() -> None:
    client, service = _client()

    response = client.get("/v2/admin/users?email=bob%40example&offset=5&limit=10")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "items": [EXPECTED_USER],
            "offset": 5,
            "limit": 10,
            "has_more": True,
        },
    }
    assert service.calls == [
        (
            "require_minimum_user_type",
            {"principal": PRINCIPAL, "minimum": UserType.ADMIN},
        ),
        (
            "list_users",
            {
                "principal": PRINCIPAL,
                "search": AdminUserSearch(email="bob@example", offset=5, limit=10),
            },
        ),
    ]


@pytest.mark.parametrize(
    "query",
    [
        "email=",
        "unknown=1",
        "limit=0",
        "offset=-1",
        "email=a&email=b",
        f"email={'a' * 321}",
    ],
)
def test_the_user_list_refuses_invalid_queries(query: str) -> None:
    client, service = _client()

    response = client.get(f"/v2/admin/users?{query}")

    assert response.status_code == 422
    assert [name for name, _kwargs in service.calls if name == "list_users"] == []


def test_admins_read_one_user_and_its_type_history() -> None:
    client, service = _client()

    read = client.get(f"/v2/admin/users/{TARGET_ID}")
    history = client.get(f"/v2/admin/users/{TARGET_ID}/user-type-changes")

    assert read.status_code == 200
    assert read.json()["result"] == {"item": EXPECTED_USER}
    assert history.status_code == 200
    assert history.json()["result"] == {
        "items": [
            {
                "id": str(CHANGE_ID),
                "user_id": str(TARGET_ID),
                "previous_user_type": "standard",
                "new_user_type": "author",
                "changed_by_user_id": str(OWNER_ID),
                "changed_by_email": "alice@example.test",
                "source": "admin_route",
                "created_at": "2026-02-01T00:00:00Z",
            }
        ]
    }
    assert ("get_user", {"principal": PRINCIPAL, "user_id": TARGET_ID}) in (
        service.calls
    )
    assert (
        "list_user_type_changes",
        {"principal": PRINCIPAL, "user_id": TARGET_ID},
    ) in service.calls


def test_admins_change_a_signed_in_users_type() -> None:
    client, service = _client()

    changed = client.patch(
        f"/v2/admin/users/{TARGET_ID}",
        json={"user_type": "author", "expected_user_type": "standard"},
    )
    refused = [
        client.patch(f"/v2/admin/users/{TARGET_ID}", json=body)
        for body in (
            {},
            {"user_type": "author"},
            {"user_type": "unauthenticated", "expected_user_type": "standard"},
            {"user_type": "editor", "expected_user_type": "standard"},
            {"user_type": "author", "expected_user_type": "unauthenticated"},
            {
                "user_type": "admin",
                "expected_user_type": "standard",
                "email": "x@example.test",
            },
        )
    ]

    assert changed.status_code == 200
    assert changed.json()["result"] == {"item": EXPECTED_USER}
    assert (
        "change_user_type",
        {
            "principal": PRINCIPAL,
            "user_id": TARGET_ID,
            "user_type": UserType.AUTHOR,
            "expected_user_type": UserType.STANDARD,
        },
    ) in service.calls
    assert [response.status_code for response in refused] == [422] * 6
    assert [name for name, _kwargs in service.calls].count("change_user_type") == 1


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (SignedInUserNotFoundError("No signed-in user has this ID"), 404),
        (LastAdminDemotionError("The last admin can't be demoted"), 409),
        (UserTypeChangedError("This user's type is now author, not standard"), 409),
        (UserTypeBelowMinimumError("Only admins may do this"), 403),
    ],
)
def test_service_refusals_map_to_http_statuses(
    error: Exception, status_code: int
) -> None:
    def refuse(name: str, kwargs: dict):
        if name == "require_minimum_user_type":
            return UserType.ADMIN
        raise error

    client, _service = _client(RecordingService(refuse))

    response = client.patch(
        f"/v2/admin/users/{TARGET_ID}",
        json={"user_type": "standard", "expected_user_type": "author"},
    )

    assert response.status_code == status_code
    assert response.json() == {"status": "error", "message": str(error)}


@pytest.mark.parametrize("principal", ["signed_in", "signed_out"])
def test_callers_below_admin_get_403_from_every_admin_route(principal: str) -> None:
    service = RecordingService(_result)
    service.error = UserTypeBelowMinimumError("Only admins may manage users' types")
    accounts = RecordingService()
    options = {} if principal == "signed_in" else {"require_user": signed_out_browser}
    client, _service = _client(
        service, v2_account_service_factory=lambda: accounts, **options
    )

    responses = [
        client.get("/v2/admin/users"),
        client.get(f"/v2/admin/users/{TARGET_ID}"),
        client.patch(
            f"/v2/admin/users/{TARGET_ID}",
            json={"user_type": "admin", "expected_user_type": "standard"},
        ),
        client.get(f"/v2/admin/users/{TARGET_ID}/user-type-changes"),
        client.delete(f"/v2/admin/users/{TARGET_ID}"),
    ]

    assert [response.status_code for response in responses] == [403] * 5
    assert {name for name, _kwargs in service.calls} == {"require_minimum_user_type"}
    assert accounts.calls == []
    expected_principal = (
        PRINCIPAL if principal == "signed_in" else UNAUTHENTICATED_PRINCIPAL
    )
    assert {call[1]["principal"] for call in service.calls} == {expected_principal}


def test_admin_routes_require_a_credential() -> None:
    client, service = _client(require_user=None)

    response = client.get("/v2/admin/users")

    assert response.status_code == 401
    assert service.calls == []


def test_any_route_can_require_a_minimum_type_and_is_refused_below_it() -> None:
    allowed = RecordingService(lambda _name, _kwargs: UserType.AUTHOR)
    refused = RecordingService()
    refused.error = UserTypeBelowMinimumError("Only authors and admins may do this")

    def require_author(service: RecordingService):
        return minimum_user_type_dependency(
            lambda: PRINCIPAL, lambda: service, UserType.AUTHOR
        )

    assert require_author(allowed)(principal=PRINCIPAL) is UserType.AUTHOR
    assert allowed.calls == [
        (
            "require_minimum_user_type",
            {"principal": PRINCIPAL, "minimum": UserType.AUTHOR},
        )
    ]
    # The application answers V2PermissionDeniedError with 403, as the admin
    # routes' tests show.
    with pytest.raises(
        V2PermissionDeniedError, match="Only authors and admins may do this"
    ):
        require_author(refused)(principal=PRINCIPAL)


def test_an_unreadable_caller_type_answers_503() -> None:
    service = RecordingService(_result)
    service.error = UserTypeCheckUnavailableError(
        "The caller's user type could not be read"
    )
    client, _service = _client(service)

    response = client.get("/v2/admin/users")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "message": "V2 user persistence is unavailable",
    }


def _deletion_client(accounts: RecordingService | None = None, **client_options):
    """Build the app with an admin caller and a recording account service."""
    accounts = accounts or RecordingService(
        AccountDeletion(user_id=TARGET_ID, auth0_subjects=())
    )
    client, user_types = _client(
        v2_account_service_factory=lambda: accounts, **client_options
    )
    return client, user_types, accounts


def test_admins_delete_a_signed_in_users_account() -> None:
    client, user_types, accounts = _deletion_client()

    response = client.delete(f"/v2/admin/users/{TARGET_ID}")

    assert response.status_code == 204
    assert response.content == b""
    assert user_types.calls == [
        (
            "require_minimum_user_type",
            {"principal": PRINCIPAL, "minimum": UserType.ADMIN},
        )
    ]
    assert accounts.calls == [
        (
            "delete_user_account_as_admin",
            {"principal": PRINCIPAL, "user_id": TARGET_ID},
        )
    ]


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (UserTypeBelowMinimumError("Only admins may do this"), 403),
        (SignedInUserNotFoundError("No signed-in user has this ID"), 404),
        (
            LastAdminDeletionError(
                "The last admin's account can't be deleted; make another user "
                "an admin first"
            ),
            409,
        ),
        (
            AccountIdentityDeletionError(
                "find them in Auth0 by the person's email",
                undeleted_auth0_user_count=1,
            ),
            502,
        ),
        (
            AccountDeletionUnavailableError(
                "Account deletion is temporarily unavailable; nothing was deleted"
            ),
            503,
        ),
    ],
)
def test_admin_account_deletion_refusals_map_to_http_statuses(
    error: Exception, status_code: int
) -> None:
    accounts = RecordingService()
    accounts.error = error
    client, _user_types, _accounts = _deletion_client(accounts)

    response = client.delete(f"/v2/admin/users/{TARGET_ID}")

    assert response.status_code == status_code
    assert response.json() == {"status": "error", "message": str(error)}


def test_admin_account_deletion_needs_a_uuid_and_a_credential() -> None:
    client, _user_types, accounts = _deletion_client()
    unauthenticated_client, _types, unauthenticated_accounts = _deletion_client(
        require_user=None
    )

    malformed = client.delete("/v2/admin/users/not-a-uuid")
    without_credential = unauthenticated_client.delete(f"/v2/admin/users/{TARGET_ID}")

    assert malformed.status_code == 422
    assert without_credential.status_code == 401
    assert accounts.calls == []
    assert unauthenticated_accounts.calls == []


def test_the_admin_account_deletion_route_documents_its_responses() -> None:
    client, _user_types, _accounts = _deletion_client()

    schema = client.get("/v2/openapi.json").json()
    operation = schema["paths"]["/v2/admin/users/{user_id}"]["delete"]

    assert set(operation["responses"]) >= {
        "204",
        "401",
        "403",
        "404",
        "409",
        "422",
        "502",
        "503",
    }
    assert "Admins only" in operation["description"]
    assert "Auth0" in operation["description"]
    assert "own account" in operation["responses"]["409"]["description"]
    assert "404" in operation["responses"]["502"]["description"]
    assert "email" in operation["responses"]["502"]["description"]
    assert "nothing was deleted" in operation["responses"]["503"]["description"]
