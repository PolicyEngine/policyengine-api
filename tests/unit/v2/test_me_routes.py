"""Native FastAPI contract tests for the signed-in account resource."""

from __future__ import annotations

import json
from uuid import UUID

import pytest

from policyengine_api.services.v2.user_accounts.types import (
    AccountDeletion,
    AccountExport,
    AccountImportResult,
    AccountRead,
    ImportSkip,
    ImportSkipReason,
)
from policyengine_api.services.v2.user_accounts.validators import (
    AccountIdentityDeletionError,
)
from policyengine_api.services.v2.user_policies.types import UserPolicyRead
from policyengine_api.services.v2.user_reports.types import UserReportRead
from tests.unit.v2.user_route_support import (
    CREATED_AT,
    OWNER_ID,
    PRINCIPAL,
    RecordingService,
    user_route_client,
)


IMPORTED_ID = UUID("00000000-0000-0000-0000-000000000065")


def _account(**changes) -> AccountRead:
    values = {
        "id": OWNER_ID,
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
    if name == "import_records":
        return AccountImportResult(
            id_map={"sup-1": IMPORTED_ID},
            skipped=(
                ImportSkip(
                    client_ref="sus-9",
                    reason=ImportSkipReason.UNKNOWN_LEGACY_REFERENCE,
                ),
                ImportSkip(client_ref=None, reason=ImportSkipReason.INVALID),
            ),
        )
    if name == "delete_account":
        return AccountDeletion(user_id=OWNER_ID, auth0_subjects=())
    if name == "update_account":
        return _account(first_name="Ada")
    return _account()


def _client(service: RecordingService | None = None):
    service = service or RecordingService(_result)
    client, _flask_calls = user_route_client(v2_account_service_factory=lambda: service)
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


def test_import_returns_id_map_and_skipped_items() -> None:
    client, service = _client()

    response = client.post(
        "/v2/me/imports?country_id=us",
        json={
            "policies": [{"client_ref": "sup-1", "legacy_policy_id": 1}],
            "simulations": [{"client_ref": "sus-9", "legacy_simulation_id": 99}],
            "reports": [{"legacy_report_id": "invalid"}],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "id_map": {"sup-1": str(IMPORTED_ID)},
            "skipped": [
                {"client_ref": "sus-9", "reason": "unknown_legacy_reference"},
                {"client_ref": None, "reason": "invalid"},
            ],
        },
    }
    import_input = service.calls[0][1]["import_input"]
    assert import_input.households == []
    assert len(import_input.reports) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"policies": [{"client_ref": f"sup-{index}"} for index in range(501)]},
        {"unknown": []},
        {"policies": ["not-an-object"]},
    ],
)
def test_import_rejects_oversized_counts_and_unknown_sections(body: dict) -> None:
    client, service = _client()

    response = client.post("/v2/me/imports?country_id=us", json=body)

    assert response.status_code == 422
    assert service.calls == []


def test_import_rejects_bodies_over_one_mebibyte() -> None:
    client, service = _client()
    body = json.dumps(
        {"policies": [{"client_ref": "sup-1", "description": "x" * 1_048_576}]}
    )

    response = client.post(
        "/v2/me/imports?country_id=us",
        content=body,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["status"] == "error"
    assert service.calls == []


def test_export_serializes_stored_rows_outside_current_input_bounds() -> None:
    long_text = "x" * 20_000
    odd_policy = UserPolicyRead(
        id=IMPORTED_ID,
        country_id="us",
        user_id=OWNER_ID,
        policy_id=None,
        legacy_policy_id=1,
        name=None,
        description=long_text,
        baseline="current-law",
        provenance={"source": "a-source-added-later", "ref": long_text, "extra": 1},
        client_ref="rf-1",
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )
    odd_report = UserReportRead(
        id=IMPORTED_ID,
        country_id="us",
        user_id=OWNER_ID,
        report_id=None,
        legacy_report_id=615,
        name=None,
        description=None,
        user_policy_id=None,
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
        last_run_at=None,
        client_ref="lfr-1",
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
