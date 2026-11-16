"""Native FastAPI contract tests for the account resource."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from policyengine_api.data.v2.models import UserType
from policyengine_api.services.v2.identity.types import AccountConversionOutcome
from policyengine_api.services.v2.identity.validators import (
    StandardUserRequiresSignInError,
)
from policyengine_api.services.v2.user_accounts.types import (
    AccountDeletion,
    AccountExport,
    AccountRead,
    AccountUpgrade,
    LatestTypeChangeRead,
)
from policyengine_api.services.v2.user_accounts.validators import (
    AccountDeletionUnavailableError,
    AccountEditRequiresSignInError,
    AccountIdentityDeletionError,
    AccountNotFoundError,
    TypeChangeNotFoundError,
)
from policyengine_api.services.v2.user_invitations.types import InvitationAcceptance
from policyengine_api.services.v2.user_invitations.validators import (
    InvitationAcceptedError,
    InvitationEmailMismatchError,
    InvitationEmailNotVerifiedError,
    InvitationEmailUnavailableError,
    InvitationExpiredError,
    InvitationRevokedError,
    InvitationTokenNotFoundError,
    InviterNotAdminError,
)
from policyengine_api.services.v2.user_policies.types import UserPolicyRead
from policyengine_api.services.v2.user_reports.types import UserReportRead
from policyengine_api.services.v2.user_types.validators import (
    LastAdminDeletionError,
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

RECORD_ID = UUID("00000000-0000-0000-0000-000000000065")
UNAUTHENTICATED_HEADERS = {"PolicyEngine-Unauthenticated-User": str(BROWSER_USER_ID)}


def _account(**changes) -> AccountRead:
    values = {
        "id": OWNER_ID,
        "user_type": "standard",
        "primary_country": "us",
        "first_name": None,
        "last_name": None,
        "email": None,
        "created_at": CREATED_AT,
    }
    values.update(changes)
    return AccountRead(**values)


def _result(name: str, _kwargs: dict):
    if name == "export_account":
        return AccountExport(
            user=_account(),
            policies=(),
            households=(),
            simulations=(),
            reports=(),
        )
    if name == "upgrade_account":
        return AccountUpgrade(
            account=_account(), outcome=AccountConversionOutcome.CONVERTED
        )
    if name == "delete_account":
        return AccountDeletion(user_id=OWNER_ID, auth0_subjects=())
    if name == "update_account":
        return _account(first_name="Ada")
    return _account()


def _client(service: RecordingService | None = None, **client_options):
    service = service or RecordingService(_result)
    client, _flask_calls = user_route_client(
        v2_account_service_factory=lambda: service, **client_options
    )
    return client, service


def test_get_me_provisions_with_the_query_country() -> None:
    client, service = _client()

    response = client.get("/v2/me?country_id=UK")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "item": {
                "id": str(OWNER_ID),
                "user_type": "standard",
                "primary_country": "us",
                "first_name": None,
                "last_name": None,
                "email": None,
                "created_at": "2026-01-01T00:00:00Z",
            },
            "latest_type_change": None,
        },
    }
    assert service.calls == [
        ("get_account", {"principal": PRINCIPAL, "country_id": "uk"})
    ]


@pytest.mark.parametrize("user_type", ["author", "admin"])
def test_account_responses_carry_an_author_or_admin_type(user_type: str) -> None:
    def typed_result(name: str, _kwargs: dict):
        account = _account(user_type=user_type)
        return {
            "export_account": AccountExport(
                user=account,
                policies=(),
                households=(),
                simulations=(),
                reports=(),
            ),
            "upgrade_account": AccountUpgrade(
                account=account, outcome=AccountConversionOutcome.MERGED
            ),
        }.get(name, account)

    client, _service = _client(RecordingService(typed_result))

    read = client.get("/v2/me?country_id=us")
    patched = client.patch("/v2/me?country_id=us", json={"first_name": "Ada"})
    exported = client.get("/v2/me/export?country_id=us")
    upgraded = client.post(
        "/v2/me/upgrade?country_id=us", headers=UNAUTHENTICATED_HEADERS
    )

    responses = (read, patched, exported, upgraded)
    assert [response.status_code for response in responses] == [200] * 4
    assert [
        read.json()["result"]["item"]["user_type"],
        patched.json()["result"]["item"]["user_type"],
        exported.json()["result"]["user"]["user_type"],
        upgraded.json()["result"]["item"]["user_type"],
    ] == [user_type] * 4


def test_patch_me_accepts_names_and_country_only() -> None:
    client, service = _client()

    accepted = client.patch(
        "/v2/me?country_id=us",
        json={"first_name": "Ada", "last_name": None, "primary_country": "uk"},
    )
    rejected = [
        client.patch("/v2/me?country_id=us", json=body)
        for body in (
            {},
            {"email": "ada@example.com"},
            {"primary_country": None},
            {"primary_country": "ca"},
            {"id": str(OWNER_ID)},
        )
    ]

    assert accepted.status_code == 200
    assert accepted.json()["result"]["item"]["first_name"] == "Ada"
    assert service.calls[0][1]["account_input"].primary_country == "uk"
    assert [response.status_code for response in rejected] == [422] * 5
    assert len(service.calls) == 1


def test_export_and_delete_me() -> None:
    client, service = _client()

    exported = client.get("/v2/me/export?country_id=us")
    deleted = client.delete("/v2/me?country_id=us")

    assert exported.status_code == 200
    assert exported.json()["result"] == {
        "user": exported.json()["result"]["user"],
        "policies": [],
        "households": [],
        "simulations": [],
        "reports": [],
    }
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert service.calls[1] == ("delete_account", {"principal": PRINCIPAL})


def test_the_last_admins_account_deletion_is_refused_with_409() -> None:
    service = RecordingService(_result)
    service.error = LastAdminDeletionError(
        "The last admin's account can't be deleted; make another user an admin first"
    )
    client, _service = _client(service)

    response = client.delete("/v2/me?country_id=us")

    assert response.status_code == 409
    assert response.json() == {"status": "error", "message": str(service.error)}


def test_failed_auth0_deletion_reports_a_retryable_upstream_error() -> None:
    service = RecordingService(_result)
    service.error = AccountIdentityDeletionError(
        "retry the request", undeleted_auth0_user_count=1
    )
    client, _service = _client(service)

    response = client.delete("/v2/me?country_id=us")

    assert response.status_code == 502
    assert response.json() == {"status": "error", "message": "retry the request"}


def test_the_account_deletion_route_documents_what_a_retry_deletes() -> None:
    client, _service = _client()

    schema = client.get("/v2/openapi.json").json()
    description = schema["paths"]["/v2/me"]["delete"]["responses"]["502"]["description"]

    assert "every one was tried" in description
    assert "only the Auth0 user of the token's own identity" in description
    assert "must be deleted in Auth0" in description


def test_unavailable_auth0_deletion_reports_that_nothing_was_deleted() -> None:
    service = RecordingService(_result)
    service.error = AccountDeletionUnavailableError(
        "Account deletion is temporarily unavailable; nothing was deleted"
    )
    client, _service = _client(service)

    response = client.delete("/v2/me?country_id=us")

    assert response.status_code == 503
    assert "nothing was deleted" in response.json()["message"]


def test_export_serializes_stored_rows_outside_current_input_bounds() -> None:
    long_text = "x" * 20_000
    odd_policy = UserPolicyRead(
        id=RECORD_ID,
        country_id="us",
        user_id=OWNER_ID,
        policy_id=None,
        legacy_policy_id=1,
        name=None,
        description=long_text,
        baseline="current-law",
        provenance={"source": "a-source-added-later", "ref": long_text, "extra": 1},
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )
    odd_report = UserReportRead(
        id=RECORD_ID,
        country_id="us",
        user_id=OWNER_ID,
        report_id=None,
        legacy_report_id=615,
        name=None,
        description=None,
        user_policy_id=None,
        baseline_user_policy_id=None,
        source_note=long_text,
        provisions=[
            {
                "path": long_text,
                "breadcrumb": "b",
                "baseline_value": 1,
                "value": 2,
                "retired_key": True,
            }
        ],
        validation={"matched_at": long_text, "map_model_version": "1"},
        budget_window_years=None,
        last_run_at=None,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )

    def result(name: str, kwargs: dict):
        if name == "export_account":
            return AccountExport(
                user=_account(),
                policies=(odd_policy,),
                households=(),
                simulations=(),
                reports=(odd_report,),
            )
        return _result(name, kwargs)

    client, _service = _client(RecordingService(result))

    exported = client.get("/v2/me/export?country_id=us")

    assert exported.status_code == 200
    body = exported.json()["result"]
    assert body["policies"][0]["provenance"] == {
        "source": "a-source-added-later",
        "ref": long_text,
        "confidence": None,
    }
    assert body["reports"][0]["provisions"][0]["path"] == long_text
    assert "retired_key" not in body["reports"][0]["provisions"][0]


def test_unauthenticated_principals_reach_every_account_operation() -> None:
    client, service = _client(require_user=signed_out_browser)

    read = client.get("/v2/me?country_id=us")
    exported = client.get("/v2/me/export?country_id=us")
    deleted = client.delete("/v2/me?country_id=us")

    assert [read.status_code, exported.status_code, deleted.status_code] == [
        200,
        200,
        204,
    ]
    assert [(name, kwargs["principal"]) for name, kwargs in service.calls] == [
        ("get_account", UNAUTHENTICATED_PRINCIPAL),
        ("export_account", UNAUTHENTICATED_PRINCIPAL),
        ("delete_account", UNAUTHENTICATED_PRINCIPAL),
    ]


def test_unauthenticated_account_items_have_no_primary_country() -> None:
    def result(_name: str, _kwargs: dict):
        return _account(
            id=BROWSER_USER_ID, user_type="unauthenticated", primary_country=None
        )

    client, _service = _client(
        RecordingService(result), require_user=signed_out_browser
    )

    response = client.get("/v2/me?country_id=us")

    assert response.status_code == 200
    item = response.json()["result"]["item"]
    assert (item["id"], item["user_type"], item["primary_country"]) == (
        str(BROWSER_USER_ID),
        "unauthenticated",
        None,
    )


def test_absent_unauthenticated_users_read_as_not_found_and_export_empty() -> None:
    def result(name: str, _kwargs: dict):
        if name == "get_account":
            msg = "The account was not found"
            raise AccountNotFoundError(msg)
        return AccountExport(
            user=None, policies=(), households=(), simulations=(), reports=()
        )

    client, _service = _client(
        RecordingService(result), require_user=signed_out_browser
    )

    read = client.get("/v2/me?country_id=us")
    exported = client.get("/v2/me/export?country_id=us")

    assert read.status_code == 404
    assert str(BROWSER_USER_ID) not in read.text
    assert exported.status_code == 200
    assert exported.json()["result"] == {
        "user": None,
        "policies": [],
        "households": [],
        "simulations": [],
        "reports": [],
    }


def test_unauthenticated_account_edits_are_forbidden() -> None:
    service = RecordingService(_result)
    service.error = AccountEditRequiresSignInError(
        "Sign in to edit your account details."
    )
    client, _service = _client(service, require_user=signed_out_browser)

    response = client.patch("/v2/me?country_id=us", json={"first_name": "Ada"})

    assert response.status_code == 403
    assert response.json() == {
        "status": "error",
        "message": "Sign in to edit your account details.",
    }


def test_a_credential_naming_a_signed_in_account_asks_the_browser_to_sign_in() -> None:
    service = RecordingService(_result)
    service.error = StandardUserRequiresSignInError("sign in to continue")
    client, _service = _client(service, require_user=signed_out_browser)

    response = client.get("/v2/me?country_id=us")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"status": "error", "message": "sign in to continue"}


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (AccountConversionOutcome.CONVERTED, "converted"),
        (AccountConversionOutcome.MERGED, "merged"),
        (AccountConversionOutcome.NONE, "none"),
    ],
)
def test_upgrade_returns_the_signed_in_account_and_outcome(
    outcome: AccountConversionOutcome, expected: str
) -> None:
    def result(_name: str, _kwargs: dict):
        return AccountUpgrade(account=_account(), outcome=outcome)

    client, service = _client(RecordingService(result))

    response = client.post(
        "/v2/me/upgrade?country_id=UK", headers=UNAUTHENTICATED_HEADERS
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "item": {
                "id": str(OWNER_ID),
                "user_type": "standard",
                "primary_country": "us",
                "first_name": None,
                "last_name": None,
                "email": None,
                "created_at": "2026-01-01T00:00:00Z",
            },
            "outcome": expected,
        },
    }
    assert service.calls == [
        (
            "upgrade_account",
            {
                "principal": PRINCIPAL,
                "unauthenticated_user_id": BROWSER_USER_ID,
                "country_id": "uk",
            },
        )
    ]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"PolicyEngine-Unauthenticated-User": "not-a-uuid"},
        {"PolicyEngine-Unauthenticated-User": str(BROWSER_USER_ID).upper()},
        {"PolicyEngine-Unauthenticated-User": BROWSER_USER_ID.hex},
        {"PolicyEngine-Unauthenticated-User": f"{{{BROWSER_USER_ID}}}"},
    ],
)
def test_upgrade_requires_a_canonical_unauthenticated_user_header(
    headers: dict[str, str],
) -> None:
    client, service = _client()

    response = client.post("/v2/me/upgrade?country_id=us", headers=headers)

    assert response.status_code == 422
    assert response.json() == {
        "status": "error",
        "message": "Invalid API v2 request",
    }
    assert service.calls == []


def test_upgrade_requires_a_bearer_access_token() -> None:
    client, service = _client(require_user=signed_out_browser)

    response = client.post(
        "/v2/me/upgrade?country_id=us", headers=UNAUTHENTICATED_HEADERS
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert service.calls == []


def test_upgrade_authentication_precedes_query_validation() -> None:
    client, service = _client(require_user=signed_out_browser)

    response = client.post("/v2/me/upgrade?country_id=zz")

    assert response.status_code == 401
    assert service.calls == []


def test_import_route_is_removed() -> None:
    client, service = _client()

    response = client.post("/v2/me/imports?country_id=us", json={"policies": []})

    assert response.status_code == 405
    assert service.calls == []


TYPE_CHANGE_ID = UUID("00000000-0000-0000-0000-000000000066")
TYPE_CHANGED_AT = datetime(2026, 11, 1, tzinfo=UTC)


def test_get_me_carries_the_latest_type_change_until_it_is_dismissed() -> None:
    def result(_name: str, _kwargs: dict):
        return _account(
            user_type="author",
            latest_type_change=LatestTypeChangeRead(
                id=TYPE_CHANGE_ID,
                previous_user_type=UserType.STANDARD,
                user_type=UserType.AUTHOR,
                changed_at=TYPE_CHANGED_AT,
            ),
        )

    client, _service = _client(RecordingService(result))

    read = client.get("/v2/me?country_id=us")
    patched = client.patch("/v2/me?country_id=us", json={"first_name": "Ada"})

    assert read.status_code == 200
    assert read.json()["result"]["latest_type_change"] == {
        "id": str(TYPE_CHANGE_ID),
        "previous_user_type": "standard",
        "user_type": "author",
        "changed_at": "2026-11-01T00:00:00Z",
    }
    # Only reading the account reports the change.
    assert set(patched.json()["result"]) == {"item"}


def _accepting_client(invitations: RecordingService, **client_options):
    client, _flask_calls = user_route_client(
        v2_user_invitation_service_factory=lambda: invitations, **client_options
    )
    return client


def test_a_signed_in_user_accepts_an_invitation_with_its_token() -> None:
    invitations = RecordingService(
        InvitationAcceptance(
            user_type=UserType.ADMIN,
            previous_user_type=UserType.STANDARD,
            type_changed=True,
        )
    )
    client = _accepting_client(invitations)

    response = client.post(
        "/v2/me/invitations/accept?country_id=UK", json={"token": "a-token"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "item": {
                "user_type": "admin",
                "previous_user_type": "standard",
                "type_changed": True,
            }
        },
    }
    assert invitations.calls == [
        (
            "accept_invitation",
            {"principal": PRINCIPAL, "token": "a-token", "country_id": "uk"},
        )
    ]


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (
            InvitationEmailUnavailableError("try again shortly"),
            503,
            "auth0_unavailable",
        ),
        (InvitationTokenNotFoundError("not valid"), 410, "invitation_not_found"),
        (InvitationRevokedError("withdrawn"), 410, "invitation_revoked"),
        (InvitationExpiredError("expired"), 410, "invitation_expired"),
        (InvitationAcceptedError("already accepted"), 410, "invitation_accepted"),
        (InviterNotAdminError("no longer an admin"), 409, "inviter_not_admin"),
        (InvitationEmailNotVerifiedError("not verified"), 409, "email_not_verified"),
        (InvitationEmailMismatchError("another address"), 403, "email_mismatch"),
    ],
)
def test_each_refused_acceptance_names_its_reason(
    error: Exception, status_code: int, code: str
) -> None:
    invitations = RecordingService()
    invitations.error = error
    client = _accepting_client(invitations)

    response = client.post(
        "/v2/me/invitations/accept?country_id=us", json={"token": "a-token"}
    )

    assert response.status_code == status_code
    assert response.json() == {
        "status": "error",
        "message": str(error),
        "code": code,
    }


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/v2/me/invitations/accept", {"token": "a-token"}),
        ("/v2/me/invitations/accept?country_id=us", {}),
        ("/v2/me/invitations/accept?country_id=us", {"token": ""}),
        ("/v2/me/invitations/accept?country_id=us", {"token": "t" * 257}),
        ("/v2/me/invitations/accept?country_id=us", {"token": "t", "email": "x"}),
    ],
)
def test_an_acceptance_needs_a_country_and_only_a_token(path: str, body: dict) -> None:
    invitations = RecordingService()
    client = _accepting_client(invitations)

    response = client.post(path, json=body)

    assert response.status_code == 422
    assert invitations.calls == []


def test_only_a_signed_in_user_accepts_an_invitation() -> None:
    invitations = RecordingService()
    client = _accepting_client(invitations, require_user=signed_out_browser)

    response = client.post(
        "/v2/me/invitations/accept?country_id=us",
        json={"token": "a-token"},
        headers=UNAUTHENTICATED_HEADERS,
    )

    assert response.status_code == 401
    assert invitations.calls == []


def test_a_signed_in_user_dismisses_a_type_change() -> None:
    client, service = _client(RecordingService())

    response = client.post(
        f"/v2/me/type-changes/{TYPE_CHANGE_ID}/dismiss?country_id=us"
    )

    assert response.status_code == 204
    assert response.content == b""
    assert service.calls == [
        (
            "dismiss_type_change",
            {"principal": PRINCIPAL, "type_change_id": TYPE_CHANGE_ID},
        )
    ]


def test_dismissing_a_type_change_the_user_doesnt_have_is_not_found() -> None:
    service = RecordingService()
    service.error = TypeChangeNotFoundError("You have no type change with this ID")
    client, _service = _client(service)

    response = client.post(
        f"/v2/me/type-changes/{TYPE_CHANGE_ID}/dismiss?country_id=us"
    )

    assert response.status_code == 404


def test_only_a_signed_in_user_dismisses_a_type_change() -> None:
    client, service = _client(RecordingService(), require_user=signed_out_browser)

    response = client.post(
        f"/v2/me/type-changes/{TYPE_CHANGE_ID}/dismiss?country_id=us",
        headers=UNAUTHENTICATED_HEADERS,
    )

    assert response.status_code == 401
    assert service.calls == []


def test_the_openapi_document_names_each_refused_acceptance_code() -> None:
    client = _accepting_client(RecordingService())

    document = client.get("/v2/openapi.json").json()
    accept = document["paths"]["/v2/me/invitations/accept"]["post"]

    assert {"200", "401", "403", "409", "410", "422", "503"} <= set(accept["responses"])

    def schemas(status: str) -> set[str]:
        schema = accept["responses"][status]["content"]["application/json"]["schema"]
        options = schema.get("anyOf", [schema])
        return {option["$ref"].rsplit("/", 1)[1] for option in options}

    # Only acceptance refusals answer 410, each with a code; 403, 409 and 503
    # may also be a machine principal's refusal, a conflict with stored
    # state or unavailable persistence, which carry none.
    assert schemas("410") == {"V2CodedErrorResponse"}
    assert (
        schemas("403")
        == schemas("409")
        == schemas("503")
        == {"V2CodedErrorResponse", "V2ErrorResponse"}
    )
    for status in ("403", "409", "410", "503"):
        assert "code" in accept["responses"][status]["description"]
