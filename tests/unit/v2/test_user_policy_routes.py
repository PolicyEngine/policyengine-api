"""Native FastAPI contract tests for signed-in v2 user-policy associations."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.services.v2.associations.validators import (
    AssociationReferenceConflictError,
    MirrorOwnedAssociationError,
)
from policyengine_api.services.v2.legacy_refs.validators import (
    LegacyReferenceNotFoundError,
)
from policyengine_api.services.v2.user_policies.types import (
    UserPolicyPage,
    UserPolicyRead,
)
from policyengine_api.services.v2.user_policies.validators import (
    AssociationCountryConflictError,
    AssociationPolicyNotFoundError,
    UserPolicyNotFoundError,
)
from tests.unit.v2.user_route_support import (
    CREATED_AT,
    OWNER_ID,
    PRINCIPAL,
    RecordingService,
    user_route_client,
)

ASSOCIATION_ID = UUID("00000000-0000-0000-0000-000000000060")
POLICY_ID = UUID("00000000-0000-0000-0000-000000000010")
PROVENANCE = {"source": "chat", "ref": "thread-1", "confidence": "exact"}


def _association_read(**changes) -> UserPolicyRead:
    values = {
        "id": ASSOCIATION_ID,
        "country_id": "us",
        "user_id": OWNER_ID,
        "policy_id": None,
        "legacy_policy_id": 95762,
        "name": "Saved reform",
        "description": "Personal note",
        "baseline": "current-law",
        "provenance": PROVENANCE,
        "created_at": CREATED_AT,
        "updated_at": CREATED_AT + timedelta(seconds=1),
    }
    values.update(changes)
    return UserPolicyRead(**values)


def _result(name: str, kwargs: dict):
    if name == "list_user_policies":
        return UserPolicyPage(
            items=(_association_read(),),
            offset=kwargs["offset"],
            limit=kwargs["limit"],
            has_more=False,
        )
    if name == "delete_user_policy":
        return None
    return _association_read()


def _client(service: RecordingService | None = None):
    service = service or RecordingService(_result)
    client, flask_calls = user_route_client(
        v2_user_policy_service_factory=lambda: service
    )
    return client, service, flask_calls


def _body(**changes) -> dict[str, object]:
    body: dict[str, object] = {
        "country_id": "us",
        "legacy_policy_id": 95762,
        "name": "Saved reform",
        "description": "Personal note",
        "baseline": "current-law",
        "provenance": PROVENANCE,
    }
    body.update(changes)
    return body


def test_create_returns_complete_contract_owned_by_the_session_user() -> None:
    client, service, flask_calls = _client()

    response = client.post("/v2/user-policies?country_id=US", json=_body())

    assert response.status_code == 201
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "item": {
                "id": str(ASSOCIATION_ID),
                "country_id": "us",
                "user_id": str(OWNER_ID),
                "policy_id": None,
                "legacy_policy_id": 95762,
                "name": "Saved reform",
                "description": "Personal note",
                "baseline": "current-law",
                "provenance": PROVENANCE,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:01Z",
            }
        },
    }
    name, kwargs = service.calls[0]
    assert name == "create_user_policy"
    assert kwargs["principal"] == PRINCIPAL
    fields = kwargs["association_input"]
    assert fields.legacy_policy_id == 95762
    assert fields.policy_id is None
    assert fields.provenance.source == "chat"
    assert not hasattr(fields, "user_id")
    assert flask_calls["count"] == 0


def test_create_accepts_a_v2_policy_reference() -> None:
    client, service, _flask_calls = _client()

    response = client.post(
        "/v2/user-policies?country_id=us",
        json={"country_id": "us", "policy_id": str(POLICY_ID)},
    )

    assert response.status_code == 201
    fields = service.calls[0][1]["association_input"]
    assert (fields.policy_id, fields.legacy_policy_id) == (POLICY_ID, None)


@pytest.mark.parametrize(
    "body",
    [
        _body(user_id=str(OWNER_ID)),
        {"country_id": "us", "name": "No reference"},
        _body(legacy_policy_id="95762"),
        _body(legacy_policy_id=0),
        _body(legacy_policy_id=True),
        _body(baseline="baseline"),
        _body(provenance={"source": "email"}),
        _body(provenance={"source": "chat", "extra": 1}),
        _body(client_ref="rf-1"),
        _body(name="x" * 256),
    ],
)
def test_create_rejects_user_ids_missing_references_and_invalid_fields(
    body: dict,
) -> None:
    client, service, _flask_calls = _client()

    response = client.post("/v2/user-policies?country_id=us", json=body)

    assert response.status_code == 422
    assert response.json() == {
        "status": "error",
        "message": "Invalid API v2 request",
    }
    assert service.calls == []


def test_create_rejects_country_mismatch() -> None:
    client, service, _flask_calls = _client()

    response = client.post("/v2/user-policies?country_id=uk", json=_body())

    assert response.status_code == 400
    assert service.calls == []


def test_detail_and_list_are_scoped_to_the_session_user() -> None:
    client, service, _flask_calls = _client()

    detail = client.get(f"/v2/user-policies/{ASSOCIATION_ID}?country_id=US")
    page = client.get(
        f"/v2/user-policies?country_id=us&policy_id={POLICY_ID}"
        "&legacy_policy_id=95762&offset=2&limit=3"
    )

    assert detail.status_code == 200
    assert page.status_code == 200
    assert service.calls == [
        (
            "get_user_policy",
            {
                "principal": PRINCIPAL,
                "country_id": "us",
                "association_id": ASSOCIATION_ID,
            },
        ),
        (
            "list_user_policies",
            {
                "principal": PRINCIPAL,
                "country_id": "us",
                "policy_id": POLICY_ID,
                "legacy_policy_id": 95762,
                "offset": 2,
                "limit": 3,
            },
        ),
    ]
    assert page.json()["result"] == {
        "items": [detail.json()["result"]["item"]],
        "offset": 2,
        "limit": 3,
        "has_more": False,
    }


def test_collection_rejects_user_ids_unknown_duplicate_and_invalid_queries() -> None:
    client, service, _flask_calls = _client()

    responses = [
        client.get(f"/v2/user-policies?country_id=us&user_id={OWNER_ID}"),
        client.get("/v2/user-policies"),
        client.get("/v2/user-policies?country_id=us&search=reform"),
        client.get("/v2/user-policies?country_id=us&country_id=uk"),
        client.get("/v2/user-policies?country_id=us&limit=501"),
        client.get("/v2/user-policies?country_id=us&legacy_policy_id=0"),
    ]

    assert [response.status_code for response in responses] == [422] * 6
    assert all(response.json()["status"] == "error" for response in responses)
    assert service.calls == []


def test_patch_repoints_legacy_reference_and_rejects_invalid_changes() -> None:
    client, service, flask_calls = _client()

    repointed = client.patch(
        f"/v2/user-policies/{ASSOCIATION_ID}?country_id=us",
        json={"legacy_policy_id": 101, "name": None},
    )
    invalid = [
        client.patch(
            f"/v2/user-policies/{ASSOCIATION_ID}?country_id=us",
            json=body,
        )
        for body in (
            {"policy_id": None},
            {"user_id": str(OWNER_ID)},
            {"client_ref": "rf-2"},
            {"legacy_policy_id": None},
            {},
        )
    ]

    assert repointed.status_code == 200
    association_input = service.calls[0][1]["association_input"]
    assert association_input.legacy_policy_id == 101
    assert association_input.model_fields_set == {"legacy_policy_id", "name"}
    assert [response.status_code for response in invalid] == [422] * 5
    assert [call[0] for call in service.calls] == ["patch_user_policy"]
    assert flask_calls["count"] == 0


def test_patch_repoints_to_a_v2_policy_reference() -> None:
    client, service, flask_calls = _client()

    repointed = client.patch(
        f"/v2/user-policies/{ASSOCIATION_ID}?country_id=us",
        json={"policy_id": str(POLICY_ID)},
    )

    assert repointed.status_code == 200
    association_input = service.calls[0][1]["association_input"]
    assert association_input.policy_id == POLICY_ID
    assert association_input.model_fields_set == {"policy_id"}
    assert flask_calls["count"] == 0


def test_delete_returns_no_content_for_the_session_user() -> None:
    client, service, _flask_calls = _client()

    response = client.delete(f"/v2/user-policies/{ASSOCIATION_ID}?country_id=us")

    assert response.status_code == 204
    assert response.content == b""
    assert service.calls == [
        (
            "delete_user_policy",
            {
                "principal": PRINCIPAL,
                "country_id": "us",
                "association_id": ASSOCIATION_ID,
            },
        )
    ]


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (AssociationCountryConflictError("different country"), 400, "country"),
        (AssociationReferenceConflictError("policy_id mismatch"), 400, "mismatch"),
        (AssociationPolicyNotFoundError("policy was not found"), 404, "not found"),
        (UserPolicyNotFoundError("association was not found"), 404, "not found"),
        (MirrorOwnedAssociationError("maintained from v1"), 409, "maintained"),
        (
            IntegrityError("statement secret", {}, Exception("credential")),
            409,
            "conflicts",
        ),
        (LegacyReferenceNotFoundError("v1 policy 9 was not found"), 422, "v1 policy"),
        (V2ConfigurationError("postgresql://secret"), 503, "unavailable"),
        (
            OperationalError("statement secret", {}, Exception("credential")),
            503,
            "unavailable",
        ),
        (SQLAlchemyError("statement secret"), 503, "unavailable"),
        (RuntimeError("credential and caller data"), 500, "operation failed"),
    ],
)
def test_failures_map_to_secret_safe_typed_errors(
    error: Exception,
    status: int,
    message: str,
) -> None:
    service = RecordingService(_result)
    service.error = error
    client, _service, _flask_calls = _client(service)

    response = client.patch(
        f"/v2/user-policies/{ASSOCIATION_ID}?country_id=us",
        json={"name": "Renamed"},
    )

    assert response.status_code == status
    assert response.json()["status"] == "error"
    assert message in response.json()["message"].lower()
    assert "secret" not in response.text
    assert "credential" not in response.text


def test_openapi_publishes_signed_in_association_contracts() -> None:
    client, _service, _flask_calls = _client()
    schema = client.get("/v2/openapi.json").json()

    collection = schema["paths"]["/v2/user-policies"]["get"]
    parameters = {item["name"]: item for item in collection["parameters"]}
    assert set(parameters) == {
        "country_id",
        "offset",
        "limit",
        "policy_id",
        "legacy_policy_id",
    }
    assert parameters["legacy_policy_id"]["schema"]["anyOf"][0]["minimum"] == 1
    assert parameters["limit"]["schema"]["maximum"] == 500
    for path, method in (
        ("/v2/user-policies", "post"),
        ("/v2/user-policies", "get"),
        ("/v2/user-policies/{association_id}", "get"),
        ("/v2/user-policies/{association_id}", "patch"),
        ("/v2/user-policies/{association_id}", "delete"),
    ):
        operation = schema["paths"][path][method]
        assert {"400", "401", "403", "404", "409", "422", "500", "503"} <= set(
            operation["responses"]
        )

    item_schema = schema["components"]["schemas"]["UserPolicyItem"]
    assert set(item_schema["required"]) == {
        "id",
        "country_id",
        "user_id",
        "policy_id",
        "legacy_policy_id",
        "name",
        "description",
        "baseline",
        "provenance",
        "created_at",
        "updated_at",
    }
    create_ref = schema["paths"]["/v2/user-policies"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    create_schema = schema["components"]["schemas"][create_ref.rsplit("/", 1)[-1]]
    assert create_schema["additionalProperties"] is False
    assert "user_id" not in create_schema["properties"]
    patch = schema["paths"]["/v2/user-policies/{association_id}"]["patch"]
    patch_ref = patch["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    patch_schema = schema["components"]["schemas"][patch_ref.rsplit("/", 1)[-1]]
    assert patch_schema["additionalProperties"] is False
    assert set(patch_schema["properties"]) == {
        "policy_id",
        "legacy_policy_id",
        "name",
        "description",
        "baseline",
        "provenance",
    }


def test_native_association_routes_do_not_use_cloud_sql_or_flask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_cloud_sql():
        msg = "Cloud SQL must not be selected"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "policyengine_api.data.orm.get_v1_session_factory",
        reject_cloud_sql,
    )
    client, service, flask_calls = _client()

    response = client.get(f"/v2/user-policies/{ASSOCIATION_ID}?country_id=us")

    assert response.status_code == 200
    assert service.calls[0][0] == "get_user_policy"
    assert flask_calls["count"] == 0
