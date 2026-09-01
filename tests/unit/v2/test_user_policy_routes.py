"""Native FastAPI contract tests for v2 user-policy associations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from flask import Flask, jsonify
import pytest
from sqlalchemy.exc import OperationalError, SQLAlchemyError, TimeoutError

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.data.v2.user_policies.persistence import (
    AssociationCountryConflictError,
    AssociationPolicyNotFoundError,
    AssociationUserNotFoundError,
)
from policyengine_api.data.v2.user_policies.query import (
    UserPolicyNotFoundError,
    UserPolicyPage,
    UserPolicyRead,
)
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)


ASSOCIATION_ID = UUID("00000000-0000-0000-0000-000000000060")
POLICY_ID = UUID("00000000-0000-0000-0000-000000000010")
USER_ID = UUID("00000000-0000-0000-0000-000000000070")
CREATED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _association_read(
    *,
    association_id: UUID = ASSOCIATION_ID,
    country_id: str = "us",
    user_id: UUID = USER_ID,
    policy_id: UUID = POLICY_ID,
    name: str | None = "Saved reform",
    description: str | None = "Personal note",
) -> UserPolicyRead:
    return UserPolicyRead(
        id=association_id,
        country_id=country_id,
        user_id=user_id,
        policy_id=policy_id,
        name=name,
        description=description,
        created_at=CREATED_AT,
        updated_at=CREATED_AT + timedelta(seconds=1),
    )


class FakeUserPolicyService:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.calls: list[tuple[str, object]] = []
        self.next_item = _association_read()

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    def create_user_policy(self, command) -> UserPolicyRead:
        self.calls.append(("create_user_policy", command))
        self._raise()
        return self.next_item

    def get_user_policy(self, **identity) -> UserPolicyRead:
        self.calls.append(("get_user_policy", identity))
        self._raise()
        return self.next_item

    def list_user_policies(self, **filters) -> UserPolicyPage:
        self.calls.append(("list_user_policies", filters))
        self._raise()
        return UserPolicyPage(
            items=(self.next_item,),
            offset=filters["offset"],
            limit=filters["limit"],
            has_more=False,
        )

    def patch_user_policy(self, **changes) -> UserPolicyRead:
        self.calls.append(("patch_user_policy", changes))
        self._raise()
        command = changes["command"]
        name = command.name if "name" in command.model_fields_set else "Saved reform"
        description = (
            command.description
            if "description" in command.model_fields_set
            else "Personal note"
        )
        return _association_read(name=name, description=description)

    def delete_user_policy(self, **identity) -> None:
        self.calls.append(("delete_user_policy", identity))
        self._raise()


def _client(
    service: FakeUserPolicyService,
) -> tuple[TestClient, dict[str, int]]:
    flask_calls = {"count": 0}
    flask_app = Flask(__name__)

    @flask_app.route("/<path:resource>", methods=["GET", "POST", "PATCH", "DELETE"])
    def fallback(resource: str):
        flask_calls["count"] += 1
        return jsonify({"source": "flask", "resource": resource})

    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        specification_provider=lambda: {},
        v2_user_policy_service_factory=lambda: service,
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    return (
        TestClient(
            create_asgi_app(
                flask_app,
                dependencies=dependencies,
                route_settings=settings,
            ),
            raise_server_exceptions=False,
        ),
        flask_calls,
    )


def _body(**changes) -> dict[str, object]:
    body: dict[str, object] = {
        "country_id": "us",
        "user_id": str(USER_ID),
        "policy_id": str(POLICY_ID),
        "name": "Saved reform",
        "description": "Personal note",
    }
    body.update(changes)
    return body


def test_create_returns_complete_distinct_association_contract() -> None:
    service = FakeUserPolicyService()
    client, flask_calls = _client(service)

    response = client.post("/v2/user-policies?country_id=US", json=_body())

    assert response.status_code == 201
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "item": {
                "id": str(ASSOCIATION_ID),
                "country_id": "us",
                "user_id": str(USER_ID),
                "policy_id": str(POLICY_ID),
                "name": "Saved reform",
                "description": "Personal note",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:01Z",
            }
        },
    }
    command = service.calls[0][1]
    assert command.user_id == USER_ID
    assert command.policy_id == POLICY_ID
    assert flask_calls["count"] == 0


def test_repeated_create_calls_service_twice_without_link_deduplication() -> None:
    service = FakeUserPolicyService()
    client, _flask_calls = _client(service)

    first = client.post("/v2/user-policies?country_id=us", json=_body())
    service.next_item = _association_read(association_id=uuid4())
    second = client.post("/v2/user-policies?country_id=us", json=_body())

    assert first.status_code == second.status_code == 201
    assert first.json()["result"]["item"]["id"] != second.json()["result"]["item"]["id"]
    assert [call[0] for call in service.calls] == [
        "create_user_policy",
        "create_user_policy",
    ]


def test_create_rejects_country_mismatch_and_invalid_fields() -> None:
    service = FakeUserPolicyService()
    client, _flask_calls = _client(service)

    mismatch = client.post("/v2/user-policies?country_id=uk", json=_body())
    invalid_user = client.post(
        "/v2/user-policies?country_id=us",
        json=_body(user_id="not-a-uuid"),
    )
    long_name = client.post(
        "/v2/user-policies?country_id=us",
        json=_body(name="x" * 256),
    )

    assert mismatch.status_code == 400
    assert invalid_user.status_code == 422
    assert long_name.status_code == 422
    assert service.calls == []


def test_detail_and_list_use_country_user_policy_and_pagination_filters() -> None:
    service = FakeUserPolicyService()
    client, _flask_calls = _client(service)

    detail = client.get(f"/v2/user-policies/{ASSOCIATION_ID}?country_id=US")
    page = client.get(
        f"/v2/user-policies?country_id=us&user_id={USER_ID}"
        f"&policy_id={POLICY_ID}&offset=2&limit=3"
    )

    assert detail.status_code == 200
    assert page.status_code == 200
    assert service.calls == [
        (
            "get_user_policy",
            {"country_id": "us", "association_id": ASSOCIATION_ID},
        ),
        (
            "list_user_policies",
            {
                "country_id": "us",
                "user_id": USER_ID,
                "policy_id": POLICY_ID,
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


def test_collection_rejects_missing_unknown_duplicate_and_invalid_queries() -> None:
    service = FakeUserPolicyService()
    client, _flask_calls = _client(service)

    responses = [
        client.get("/v2/user-policies?country_id=us"),
        client.get(f"/v2/user-policies?country_id=us&user_id={USER_ID}&search=reform"),
        client.get(f"/v2/user-policies?country_id=us&country_id=uk&user_id={USER_ID}"),
        client.get(f"/v2/user-policies?country_id=us&user_id={USER_ID}&limit=501"),
    ]

    assert [response.status_code for response in responses] == [422] * 4
    assert all(response.json()["status"] == "error" for response in responses)
    assert service.calls == []


def test_patch_supports_explicit_null_and_rejects_identity_or_empty_changes() -> None:
    service = FakeUserPolicyService()
    client, flask_calls = _client(service)

    cleared = client.patch(
        f"/v2/user-policies/{ASSOCIATION_ID}?country_id=us",
        json={"name": None},
    )
    identity = client.patch(
        f"/v2/user-policies/{ASSOCIATION_ID}?country_id=us",
        json={"policy_id": str(uuid4())},
    )
    empty = client.patch(
        f"/v2/user-policies/{ASSOCIATION_ID}?country_id=us",
        json={},
    )

    assert cleared.status_code == 200
    assert cleared.json()["result"]["item"]["name"] is None
    assert identity.status_code == 422
    assert empty.status_code == 422
    assert [call[0] for call in service.calls] == ["patch_user_policy"]
    assert flask_calls["count"] == 0


def test_delete_returns_no_content_and_uses_country_scoped_identity() -> None:
    service = FakeUserPolicyService()
    client, flask_calls = _client(service)

    response = client.delete(f"/v2/user-policies/{ASSOCIATION_ID}?country_id=us")

    assert response.status_code == 204
    assert response.content == b""
    assert service.calls == [
        (
            "delete_user_policy",
            {"country_id": "us", "association_id": ASSOCIATION_ID},
        )
    ]
    assert flask_calls["count"] == 0


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (AssociationCountryConflictError("different country"), 400, "country"),
        (AssociationPolicyNotFoundError("policy was not found"), 404, "not found"),
        (AssociationUserNotFoundError("user was not found"), 404, "not found"),
        (UserPolicyNotFoundError("association was not found"), 404, "not found"),
        (V2ConfigurationError("postgresql://secret"), 503, "unavailable"),
        (
            OperationalError("statement secret", {}, Exception("credential")),
            503,
            "unavailable",
        ),
        (TimeoutError("pool timeout"), 503, "unavailable"),
        (SQLAlchemyError("statement secret"), 503, "unavailable"),
        (RuntimeError("credential and caller data"), 500, "operation failed"),
    ],
)
def test_association_failures_map_to_secret_safe_typed_errors(
    error: Exception,
    status: int,
    message: str,
) -> None:
    service = FakeUserPolicyService()
    service.error = error
    client, _flask_calls = _client(service)

    response = client.get(f"/v2/user-policies/{ASSOCIATION_ID}?country_id=us")

    assert response.status_code == status
    assert response.json()["status"] == "error"
    assert message in response.json()["message"].lower()
    assert "secret" not in response.text
    assert "credential" not in response.text


def test_openapi_publishes_complete_no_auth_association_contracts() -> None:
    service = FakeUserPolicyService()
    client, _flask_calls = _client(service)
    schema = client.get("/v2/openapi.json").json()

    assert {
        path for path in schema["paths"] if path.startswith("/v2/user-policies")
    } == {
        "/v2/user-policies",
        "/v2/user-policies/{association_id}",
    }
    collection = schema["paths"]["/v2/user-policies"]["get"]
    parameters = {item["name"]: item for item in collection["parameters"]}
    assert parameters["country_id"]["required"] is True
    assert parameters["user_id"]["required"] is True
    assert "does not prove caller control" in parameters["user_id"]["description"]
    assert parameters["user_id"]["schema"]["format"] == "uuid"
    assert parameters["limit"]["schema"]["maximum"] == 500
    assert set(schema["paths"]["/v2/user-policies"]) == {"get", "post"}
    assert set(schema["paths"]["/v2/user-policies/{association_id}"]) == {
        "get",
        "patch",
        "delete",
    }

    for path, method in (
        ("/v2/user-policies", "post"),
        ("/v2/user-policies", "get"),
        ("/v2/user-policies/{association_id}", "get"),
        ("/v2/user-policies/{association_id}", "patch"),
        ("/v2/user-policies/{association_id}", "delete"),
    ):
        operation = schema["paths"][path][method]
        assert "security" not in operation
        assert {"400", "404", "409", "422", "500", "503"} <= set(operation["responses"])

    item_schema = schema["components"]["schemas"]["UserPolicyItem"]
    assert set(item_schema["required"]) == {
        "id",
        "country_id",
        "user_id",
        "policy_id",
        "name",
        "description",
        "created_at",
        "updated_at",
    }
    patch = schema["paths"]["/v2/user-policies/{association_id}"]["patch"]
    patch_ref = patch["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    patch_schema = schema["components"]["schemas"][patch_ref.rsplit("/", 1)[-1]]
    assert patch_schema["additionalProperties"] is False
    assert set(patch_schema["properties"]) == {"name", "description"}


def test_native_association_routes_do_not_use_cloud_sql_or_flask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_cloud_sql():
        raise AssertionError("Cloud SQL must not be selected")

    monkeypatch.setattr(
        "policyengine_api.data.orm.get_v1_session_factory",
        reject_cloud_sql,
    )
    service = FakeUserPolicyService()
    client, flask_calls = _client(service)

    response = client.get(f"/v2/user-policies/{ASSOCIATION_ID}?country_id=us")

    assert response.status_code == 200
    assert service.calls[0][0] == "get_user_policy"
    assert flask_calls["count"] == 0
