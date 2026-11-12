"""Native FastAPI contract tests for admins' user-type routes and minimum types."""

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
from policyengine_api.services.v2.user_accounts.types import (
    AccountExport,
    AccountRead,
)
from policyengine_api.services.v2.user_households.types import UserHouseholdRead
from policyengine_api.services.v2.user_policies.types import UserPolicyRead
from policyengine_api.services.v2.user_reports.types import UserReportRead
from policyengine_api.services.v2.user_simulations.types import UserSimulationRead
from policyengine_api.services.v2.user_types.types import (
    MAXIMUM_EMAIL_SEARCH_MATCHES,
    AdminUserPage,
    AdminUserRead,
    AdminUserSearch,
    UserTypeChangeRead,
)
from policyengine_api.services.v2.user_types.validators import (
    AdminUserEmailSearchRefusedError,
    AdminUserProfilesUnavailableError,
    LastAdminDemotionError,
    SignedInUserNotFoundError,
    UserTypeBelowMinimumError,
    UserTypeChangedError,
    UserTypeCheckUnavailableError,
)
from tests.unit.v2.user_route_support import (
    BROWSER_USER_ID,
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
SAVED_POLICY_ID = UUID("00000000-0000-0000-0000-000000000083")
SAVED_HOUSEHOLD_ID = UUID("00000000-0000-0000-0000-000000000084")
SAVED_SIMULATION_ID = UUID("00000000-0000-0000-0000-000000000085")
SAVED_REPORT_ID = UUID("00000000-0000-0000-0000-000000000086")
LAST_SEEN_AT = datetime(2026, 2, 1, tzinfo=UTC)
SAVED_ITEMS_PATH = f"/v2/admin/users/{TARGET_ID}/saved-items"


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


def _saved_items() -> AccountExport:
    """Return the target user and one saved record of each kind, in two countries."""
    return AccountExport(
        user=AccountRead(
            id=TARGET_ID,
            user_type="author",
            primary_country="uk",
            first_name="Bob",
            last_name=None,
            email="bob@example.test",
            created_at=CREATED_AT,
        ),
        policies=(
            UserPolicyRead(
                id=SAVED_POLICY_ID,
                country_id="uk",
                user_id=TARGET_ID,
                policy_id=None,
                legacy_policy_id=7,
                name="Bob's reform",
                description=None,
                baseline="current-law",
                provenance=None,
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            ),
        ),
        households=(
            UserHouseholdRead(
                id=SAVED_HOUSEHOLD_ID,
                country_id="us",
                user_id=TARGET_ID,
                household_id=None,
                legacy_household_id=10,
                name=None,
                description=None,
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            ),
        ),
        simulations=(
            UserSimulationRead(
                id=SAVED_SIMULATION_ID,
                country_id="us",
                user_id=TARGET_ID,
                simulation_id=None,
                legacy_simulation_id=613,
                name=None,
                description=None,
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            ),
        ),
        reports=(
            UserReportRead(
                id=SAVED_REPORT_ID,
                country_id="uk",
                user_id=TARGET_ID,
                report_id=None,
                legacy_report_id=615,
                name=None,
                description=None,
                user_policy_id=SAVED_POLICY_ID,
                baseline_user_policy_id=None,
                source_note=None,
                provisions=None,
                validation=None,
                budget_window_years=None,
                last_run_at=None,
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            ),
        ),
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
    if name in {"get_user_saved_items", "export_account"}:
        return _saved_items()
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


def test_admins_read_a_users_saved_items_as_its_own_export_returns_them() -> None:
    service = RecordingService(_result)
    client, _service = _client(service, v2_account_service_factory=lambda: service)

    saved_items = client.get(SAVED_ITEMS_PATH)
    own_export = client.get("/v2/me/export?country_id=us")

    assert saved_items.status_code == 200
    assert saved_items.json() == own_export.json()
    result = saved_items.json()["result"]
    assert result["user"]["id"] == str(TARGET_ID)
    assert [
        (kind, item["id"], item["country_id"])
        for kind in ("policies", "households", "simulations", "reports")
        for item in result[kind]
    ] == [
        ("policies", str(SAVED_POLICY_ID), "uk"),
        ("households", str(SAVED_HOUSEHOLD_ID), "us"),
        ("simulations", str(SAVED_SIMULATION_ID), "us"),
        ("reports", str(SAVED_REPORT_ID), "uk"),
    ]
    assert service.calls[:2] == [
        (
            "require_minimum_user_type",
            {"principal": PRINCIPAL, "minimum": UserType.ADMIN},
        ),
        ("get_user_saved_items", {"principal": PRINCIPAL, "user_id": TARGET_ID}),
    ]


def test_saved_items_of_an_unauthenticated_or_absent_user_are_not_found() -> None:
    not_found_error = SignedInUserNotFoundError("No signed-in user has this ID")

    def refuse(name: str, kwargs: dict):
        if name == "get_user_saved_items":
            raise not_found_error
        return _result(name, kwargs)

    client, service = _client(RecordingService(refuse))

    not_found = client.get(f"/v2/admin/users/{BROWSER_USER_ID}/saved-items")
    malformed = client.get("/v2/admin/users/not-a-uuid/saved-items")

    assert not_found.status_code == 404
    assert not_found.json() == {
        "status": "error",
        "message": "No signed-in user has this ID",
    }
    assert str(BROWSER_USER_ID) not in not_found.text
    assert malformed.status_code == 422
    assert [
        kwargs["user_id"]
        for name, kwargs in service.calls
        if name == "get_user_saved_items"
    ] == [BROWSER_USER_ID]


def test_openapi_publishes_the_saved_items_route_with_the_export_result() -> None:
    client, _service = _client()

    schema = client.get("/v2/openapi.json").json()

    # Read-only: the path has no other operation.
    assert set(schema["paths"]["/v2/admin/users/{user_id}/saved-items"]) == {"get"}
    operation = schema["paths"]["/v2/admin/users/{user_id}/saved-items"]["get"]
    assert {"200", "401", "403", "404", "422", "500", "503"} <= set(
        operation["responses"]
    )
    success_ref = operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    success_schema = schema["components"]["schemas"][success_ref.rsplit("/", 1)[-1]]
    assert success_schema["properties"]["result"]["$ref"].endswith("/MeExportResult")
    assert "Admins only" in operation["description"]


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
    options = {} if principal == "signed_in" else {"require_user": signed_out_browser}
    client, _service = _client(service, **options)

    responses = [
        client.get("/v2/admin/users"),
        client.get(f"/v2/admin/users/{TARGET_ID}"),
        client.patch(
            f"/v2/admin/users/{TARGET_ID}",
            json={"user_type": "admin", "expected_user_type": "standard"},
        ),
        client.get(f"/v2/admin/users/{TARGET_ID}/user-type-changes"),
        client.get(SAVED_ITEMS_PATH),
    ]

    assert [response.status_code for response in responses] == [403] * 5
    assert {name for name, _kwargs in service.calls} == {"require_minimum_user_type"}
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


def test_an_email_search_answers_503_when_auth0_profiles_are_unavailable() -> None:
    error = AdminUserProfilesUnavailableError(
        "Users can't be searched by email now: their emails could not be read "
        "from Auth0. Try again shortly."
    )

    def unavailable(name: str, kwargs: dict):
        if name == "require_minimum_user_type":
            return UserType.ADMIN
        raise error

    client, _service = _client(RecordingService(unavailable))

    response = client.get("/v2/admin/users?email=bob")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "message": str(error)}


def test_openapi_says_where_admins_read_emails_and_names() -> None:
    client, _service = _client()

    document = client.get("/v2/openapi.json").json()

    list_users = document["paths"]["/v2/admin/users"]["get"]
    read_user = document["paths"]["/v2/admin/users/{user_id}"]["get"]
    user_item = document["components"]["schemas"]["AdminUserItem"]
    change_item = document["components"]["schemas"]["UserTypeChangeItem"]
    for description in (
        list_users["description"],
        read_user["description"],
        user_item["description"],
        change_item["description"],
    ):
        assert "Auth0" in description
    assert "stored" in user_item["description"]
    assert "email search" in list_users["responses"]["503"]["description"]
    (email,) = [
        parameter
        for parameter in list_users["parameters"]
        if parameter["name"] == "email"
    ]
    # The optional parameter's text is on its string schema.
    (email_text, _no_email) = email["schema"]["anyOf"]
    # The route and its email parameter say which searches are refused.
    for description in (list_users["description"], email_text["description"]):
        assert "< or >" in description
        assert f"more than {MAXIMUM_EMAIL_SEARCH_MATCHES}" in description
    assert "1,000" not in list_users["description"]


@pytest.mark.parametrize(
    "message",
    [
        f"More than {MAXIMUM_EMAIL_SEARCH_MATCHES} users match that email text; "
        "enter more of it",
        "Email search text can't contain < or >: no email address holds them",
    ],
)
def test_refused_email_searches_answer_422(message: str) -> None:
    def refuse(name: str, kwargs: dict):
        if name == "require_minimum_user_type":
            return UserType.ADMIN
        raise AdminUserEmailSearchRefusedError(message)

    client, _service = _client(RecordingService(refuse))

    response = client.get("/v2/admin/users?email=gmail")

    assert response.status_code == 422
    assert response.json() == {"status": "error", "message": message}
