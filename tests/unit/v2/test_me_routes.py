"""Native FastAPI contract tests for the account resource."""

from __future__ import annotations

from uuid import UUID

import pytest

from policyengine_api.services.v2.identity.types import AccountConversionOutcome
from policyengine_api.services.v2.identity.validators import (
    StandardUserRequiresSignInError,
)
from policyengine_api.services.v2.user_accounts.types import (
    AccountDeletion,
    AccountExport,
    AccountRead,
    AccountUpgrade,
)
from policyengine_api.services.v2.user_accounts.validators import (
    AccountDeletionUnavailableError,
    AccountEditRequiresSignInError,
    AccountIdentityDeletionError,
    AccountNotFoundError,
)
from policyengine_api.services.v2.user_policies.types import UserPolicyRead
from policyengine_api.services.v2.user_reports.types import UserReportRead
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


def _result(name: str, kwargs: dict):
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
            }
        },
    }
    assert service.calls == [
        ("get_account", {"principal": PRINCIPAL, "country_id": "uk"})
    ]


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


def test_failed_auth0_deletion_reports_a_retryable_upstream_error() -> None:
    service = RecordingService(_result)
    service.error = AccountIdentityDeletionError("retry the request")
    client, _service = _client(service)

    response = client.delete("/v2/me?country_id=us")

    assert response.status_code == 502
    assert response.json() == {"status": "error", "message": "retry the request"}


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
    def result(name: str, kwargs: dict):
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
    def result(name: str, kwargs: dict):
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
    def result(name: str, kwargs: dict):
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
