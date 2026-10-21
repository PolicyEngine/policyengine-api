"""Native FastAPI contract tests for signed-in v2 user-household associations."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.services.v2.associations.validators import (
    AssociationReferenceConflictError,
)
from policyengine_api.services.v2.legacy_refs.validators import (
    LegacyReferenceNotFoundError,
)
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdFilter,
    UserHouseholdPage,
    UserHouseholdRead,
)
from policyengine_api.services.v2.user_households.validators import (
    AssociationCountryConflictError,
    AssociationHouseholdNotFoundError,
    UserHouseholdNotFoundError,
)
from tests.unit.v2.user_route_support import (
    CREATED_AT,
    OWNER_ID,
    PRINCIPAL,
    RecordingService,
    user_route_client,
)

ASSOCIATION_ID = UUID("00000000-0000-0000-0000-000000000061")
HOUSEHOLD_ID = UUID("00000000-0000-0000-0000-000000000011")


def _association_read(**changes) -> UserHouseholdRead:
    values = {
        "id": ASSOCIATION_ID,
        "country_id": "us",
        "user_id": OWNER_ID,
        "household_id": HOUSEHOLD_ID,
        "legacy_household_id": 123,
        "name": "Family",
        "description": None,
        "created_at": CREATED_AT,
        "updated_at": CREATED_AT + timedelta(seconds=1),
    }
    values.update(changes)
    return UserHouseholdRead(**values)


def _result(name: str, kwargs: dict):
    if name == "list_user_households":
        return UserHouseholdPage(
            items=(_association_read(),),
            offset=kwargs["offset"],
            limit=kwargs["limit"],
            has_more=True,
        )
    if name == "delete_user_household":
        return None
    return _association_read()


def _client(service: RecordingService | None = None):
    service = service or RecordingService(_result)
    client, flask_calls = user_route_client(
        v2_user_household_service_factory=lambda: service
    )
    return client, service, flask_calls


def test_create_returns_complete_contract_owned_by_the_session_user() -> None:
    client, service, _flask_calls = _client()

    response = client.post(
        "/v2/user-households?country_id=us",
        json={
            "country_id": "us",
            "legacy_household_id": 123,
            "name": "Family",
        },
    )

    assert response.status_code == 201
    assert response.json()["result"]["item"] == {
        "id": str(ASSOCIATION_ID),
        "country_id": "us",
        "user_id": str(OWNER_ID),
        "household_id": str(HOUSEHOLD_ID),
        "legacy_household_id": 123,
        "name": "Family",
        "description": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:01Z",
    }
    name, kwargs = service.calls[0]
    assert name == "create_user_household"
    assert kwargs["principal"] == PRINCIPAL
    assert kwargs["association_input"].legacy_household_id == 123


@pytest.mark.parametrize(
    "body",
    [
        {"country_id": "us", "legacy_household_id": 1, "user_id": str(OWNER_ID)},
        {"country_id": "us", "name": "No reference"},
        {"country_id": "us", "legacy_household_id": -4},
        {"country_id": "us", "household_id": "not-a-uuid"},
    ],
)
def test_create_rejects_user_ids_and_invalid_references(body: dict) -> None:
    client, service, _flask_calls = _client()

    response = client.post("/v2/user-households?country_id=us", json=body)

    assert response.status_code == 422
    assert service.calls == []


def test_create_rejects_country_mismatch() -> None:
    client, service, _flask_calls = _client()

    response = client.post(
        "/v2/user-households?country_id=uk",
        json={"country_id": "us", "household_id": str(HOUSEHOLD_ID)},
    )

    assert response.status_code == 400
    assert service.calls == []


def test_list_and_patch_use_the_session_user_and_legacy_fields() -> None:
    client, service, _flask_calls = _client()

    page = client.get(
        "/v2/user-households?country_id=us&legacy_household_id=123&limit=1"
    )
    patched = client.patch(
        f"/v2/user-households/{ASSOCIATION_ID}?country_id=us",
        json={"legacy_household_id": 124},
    )
    user_filter = client.get(f"/v2/user-households?country_id=us&user_id={OWNER_ID}")
    invalid_patches = [
        client.patch(
            f"/v2/user-households/{ASSOCIATION_ID}?country_id=us",
            json=body,
        )
        for body in (
            {"household_id": None},
            {"household_id": "not-a-uuid"},
            {"user_id": str(OWNER_ID)},
            {"legacy_household_id": None},
            {},
        )
    ]

    assert page.status_code == 200
    assert page.json()["result"]["has_more"] is True
    assert patched.status_code == 200
    assert user_filter.status_code == 422
    assert [response.status_code for response in invalid_patches] == [422] * 5
    assert service.calls[0] == (
        "list_user_households",
        {
            "principal": PRINCIPAL,
            "country_id": "us",
            "household_filter": UserHouseholdFilter(
                household_id=None, legacy_household_id=123
            ),
            "offset": 0,
            "limit": 1,
        },
    )
    assert service.calls[1][1]["association_input"].legacy_household_id == 124
    assert len(service.calls) == 2


def test_patch_repoints_to_a_v2_household_reference() -> None:
    client, service, flask_calls = _client()

    repointed = client.patch(
        f"/v2/user-households/{ASSOCIATION_ID}?country_id=us",
        json={"household_id": str(HOUSEHOLD_ID)},
    )

    assert repointed.status_code == 200
    assert service.calls[0][0] == "patch_user_household"
    association_input = service.calls[0][1]["association_input"]
    assert association_input.household_id == HOUSEHOLD_ID
    assert association_input.model_fields_set == {"household_id"}
    assert flask_calls["count"] == 0


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (AssociationCountryConflictError("country"), 400),
        (AssociationHouseholdNotFoundError("household was not found"), 404),
        (UserHouseholdNotFoundError("association was not found"), 404),
        (IntegrityError("secret", {}, Exception("credential")), 409),
        (LegacyReferenceNotFoundError("v1 household 9 was not found"), 422),
        (V2ConfigurationError("postgresql://secret"), 503),
        (SQLAlchemyError("secret"), 503),
        (RuntimeError("credential"), 500),
    ],
)
def test_failures_map_to_secret_safe_typed_errors(
    error: Exception, status: int
) -> None:
    service = RecordingService(_result)
    service.error = error
    client, _service, _flask_calls = _client(service)

    response = client.delete(f"/v2/user-households/{ASSOCIATION_ID}?country_id=us")

    assert response.status_code == status
    assert response.json()["status"] == "error"
    assert "secret" not in response.text
    assert "credential" not in response.text


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (AssociationCountryConflictError("different country"), 400, "country"),
        (
            AssociationReferenceConflictError("household_id mismatch"),
            400,
            "mismatch",
        ),
        (AssociationHouseholdNotFoundError("household was not found"), 404, "not"),
        (UserHouseholdNotFoundError("association was not found"), 404, "not"),
        (LegacyReferenceNotFoundError("v1 household 9 was not found"), 422, "v1"),
    ],
)
def test_repoint_failures_map_to_typed_errors(
    error: Exception, status: int, message: str
) -> None:
    service = RecordingService(_result)
    service.error = error
    client, _service, _flask_calls = _client(service)

    response = client.patch(
        f"/v2/user-households/{ASSOCIATION_ID}?country_id=us",
        json={"household_id": str(HOUSEHOLD_ID), "legacy_household_id": 9},
    )

    assert response.status_code == status
    assert response.json()["status"] == "error"
    assert message in response.json()["message"].lower()


def test_patch_preflight_and_native_routes_avoid_cloud_sql_and_flask(
    monkeypatch,
) -> None:
    def reject_cloud_sql():
        msg = "Cloud SQL must not be selected"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "policyengine_api.data.orm.get_v1_session_factory",
        reject_cloud_sql,
    )
    client, service, flask_calls = _client()
    preflight = client.options(
        f"/v2/user-households/{ASSOCIATION_ID}",
        headers={
            "Origin": "https://app.example",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    detail = client.get(f"/v2/user-households/{ASSOCIATION_ID}?country_id=us")

    assert preflight.status_code == 200
    assert "PATCH" in preflight.headers["access-control-allow-methods"]
    assert "authorization" in preflight.headers["access-control-allow-headers"]
    assert detail.status_code == 200
    assert service.calls[0][0] == "get_user_household"
    assert flask_calls["count"] == 0


def test_openapi_publishes_signed_in_household_contract() -> None:
    client, _service, _flask_calls = _client()
    schema = client.get("/v2/openapi.json").json()

    collection = schema["paths"]["/v2/user-households"]["get"]
    assert {item["name"] for item in collection["parameters"]} == {
        "country_id",
        "offset",
        "limit",
        "household_id",
        "legacy_household_id",
    }
    patch = schema["paths"]["/v2/user-households/{association_id}"]["patch"]
    patch_ref = patch["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    patch_schema = schema["components"]["schemas"][patch_ref.rsplit("/", 1)[-1]]
    assert patch_schema["additionalProperties"] is False
    assert set(patch_schema["properties"]) == {
        "household_id",
        "legacy_household_id",
        "name",
        "description",
    }
    assert set(schema["components"]["schemas"]["UserHouseholdItem"]["required"]) == {
        "id",
        "country_id",
        "user_id",
        "household_id",
        "legacy_household_id",
        "name",
        "description",
        "created_at",
        "updated_at",
    }
