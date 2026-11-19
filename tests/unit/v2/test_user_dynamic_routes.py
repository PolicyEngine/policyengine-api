"""Native FastAPI contract tests for users' saved dynamics (``/v2/user-dynamics``)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest
from policyengine_api.services.v2.user_dynamics.types import (
    UserDynamicFilter,
    UserDynamicPage,
    UserDynamicRead,
)
from policyengine_api.services.v2.user_dynamics.validators import (
    AssociationDynamicCountryConflictError,
    AssociationDynamicNotFoundError,
    UserDynamicNotFoundError,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from policyengine_api.data.v2.settings import V2ConfigurationError
from tests.unit.v2.user_route_support import (
    CREATED_AT,
    OWNER_ID,
    PRINCIPAL,
    UNAUTHENTICATED_PRINCIPAL,
    RecordingService,
    signed_out_browser,
    user_route_client,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi.testclient import TestClient

SAVED_DYNAMIC_ID = UUID("00000000-0000-0000-0000-000000000061")
DYNAMIC_ID = UUID("00000000-0000-0000-0000-000000000011")
OTHER_DYNAMIC_ID = UUID("00000000-0000-0000-0000-000000000012")
DETAIL_PATH = f"/v2/user-dynamics/{SAVED_DYNAMIC_ID}?country_id=us"


def _saved_dynamic_read(**changes: Any) -> UserDynamicRead:
    values: dict[str, Any] = {
        "id": SAVED_DYNAMIC_ID,
        "country_id": "us",
        "user_id": OWNER_ID,
        "dynamic_id": DYNAMIC_ID,
        "name": "CBO labour supply responses",
        "description": "Income and substitution elasticities",
        "created_at": CREATED_AT,
        "updated_at": CREATED_AT + timedelta(seconds=1),
    }
    values.update(changes)
    return UserDynamicRead(**values)


def _result(
    name: str, kwargs: dict[str, Any]
) -> UserDynamicRead | UserDynamicPage | None:
    if name == "list_user_dynamics":
        return UserDynamicPage(
            items=(_saved_dynamic_read(),),
            offset=kwargs["offset"],
            limit=kwargs["limit"],
            has_more=False,
        )
    if name == "delete_user_dynamic":
        return None
    return _saved_dynamic_read()


def _client(
    service: RecordingService | None = None,
    *,
    require_user: Callable[..., Any] | None = None,
) -> tuple[TestClient, RecordingService, dict[str, int]]:
    recording_service = service or RecordingService(_result)
    principal_overrides = {} if require_user is None else {"require_user": require_user}
    client, flask_calls = user_route_client(
        v2_user_dynamic_service_factory=lambda: recording_service,
        **principal_overrides,
    )
    return client, recording_service, flask_calls


def _body(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "country_id": "us",
        "dynamic_id": str(DYNAMIC_ID),
        "name": "CBO labour supply responses",
        "description": "Income and substitution elasticities",
    }
    body.update(changes)
    return body


def test_create_returns_the_saved_dynamic_owned_by_the_session_user() -> None:
    client, service, flask_calls = _client()

    response = client.post("/v2/user-dynamics?country_id=US", json=_body())

    assert response.status_code == 201
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "item": {
                "id": str(SAVED_DYNAMIC_ID),
                "country_id": "us",
                "user_id": str(OWNER_ID),
                "dynamic_id": str(DYNAMIC_ID),
                "name": "CBO labour supply responses",
                "description": "Income and substitution elasticities",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:01Z",
            }
        },
    }
    name, kwargs = service.calls[0]
    assert name == "create_user_dynamic"
    assert kwargs["principal"] == PRINCIPAL
    fields = kwargs["association_input"]
    assert (fields.country_id, fields.dynamic_id) == ("us", DYNAMIC_ID)
    assert not hasattr(fields, "user_id")
    assert flask_calls["count"] == 0


def test_a_signed_out_browser_saves_dynamics_as_itself() -> None:
    client, service, _flask_calls = _client(require_user=signed_out_browser)

    response = client.post("/v2/user-dynamics?country_id=us", json=_body())

    assert response.status_code == 201
    assert service.calls[0][1]["principal"] == UNAUTHENTICATED_PRINCIPAL


@pytest.mark.parametrize(
    "body",
    [
        _body(user_id=str(OWNER_ID)),
        {"country_id": "us", "name": "No dynamic"},
        _body(dynamic_id=None),
        _body(dynamic_id="not-a-uuid"),
        _body(legacy_policy_id=1),
        _body(baseline="current-law"),
        _body(name="x" * 256),
        _body(description="x" * 10_001),
    ],
)
def test_create_rejects_owners_missing_dynamics_and_invalid_fields(
    body: dict[str, object],
) -> None:
    client, service, _flask_calls = _client()

    response = client.post("/v2/user-dynamics?country_id=us", json=body)

    assert response.status_code == 422
    assert response.json() == {
        "status": "error",
        "message": "Invalid API v2 request",
    }
    assert service.calls == []


def test_create_rejects_a_body_country_unlike_the_query_country() -> None:
    client, service, _flask_calls = _client()

    response = client.post("/v2/user-dynamics?country_id=uk", json=_body())

    assert response.status_code == 400
    assert service.calls == []


def test_detail_and_list_are_scoped_to_the_session_user() -> None:
    client, service, _flask_calls = _client()

    detail = client.get(f"/v2/user-dynamics/{SAVED_DYNAMIC_ID}?country_id=US")
    page = client.get(
        f"/v2/user-dynamics?country_id=us&dynamic_id={DYNAMIC_ID}&offset=2&limit=3"
    )

    assert detail.status_code == 200
    assert page.status_code == 200
    assert service.calls == [
        (
            "get_user_dynamic",
            {
                "principal": PRINCIPAL,
                "country_id": "us",
                "association_id": SAVED_DYNAMIC_ID,
            },
        ),
        (
            "list_user_dynamics",
            {
                "principal": PRINCIPAL,
                "country_id": "us",
                "dynamic_filter": UserDynamicFilter(dynamic_id=DYNAMIC_ID),
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


def test_collection_rejects_owners_unknown_duplicate_and_invalid_queries() -> None:
    client, service, _flask_calls = _client()

    responses = [
        client.get(f"/v2/user-dynamics?country_id=us&user_id={OWNER_ID}"),
        client.get("/v2/user-dynamics"),
        client.get("/v2/user-dynamics?country_id=us&legacy_policy_id=1"),
        client.get("/v2/user-dynamics?country_id=us&country_id=uk"),
        client.get("/v2/user-dynamics?country_id=us&limit=501"),
        client.get("/v2/user-dynamics?country_id=us&dynamic_id=not-a-uuid"),
    ]

    assert [response.status_code for response in responses] == [422] * 6
    assert all(response.json()["status"] == "error" for response in responses)
    assert service.calls == []


def test_patch_renames_or_repoints_and_rejects_invalid_changes() -> None:
    client, service, flask_calls = _client()

    renamed = client.patch(DETAIL_PATH, json={"name": "Renamed", "description": None})
    repointed = client.patch(DETAIL_PATH, json={"dynamic_id": str(OTHER_DYNAMIC_ID)})
    invalid = [
        client.patch(DETAIL_PATH, json=body)
        for body in (
            {"dynamic_id": None},
            {"dynamic_id": "not-a-uuid"},
            {"user_id": str(OWNER_ID)},
            {"country_id": "uk"},
            {"legacy_policy_id": 1},
            {},
        )
    ]

    assert renamed.status_code == 200
    assert repointed.status_code == 200
    rename_input = service.calls[0][1]["association_input"]
    repoint_input = service.calls[1][1]["association_input"]
    assert rename_input.model_fields_set == {"name", "description"}
    assert (rename_input.name, rename_input.description) == ("Renamed", None)
    assert repoint_input.model_fields_set == {"dynamic_id"}
    assert repoint_input.dynamic_id == OTHER_DYNAMIC_ID
    assert [response.status_code for response in invalid] == [422] * 6
    assert [call[0] for call in service.calls] == [
        "patch_user_dynamic",
        "patch_user_dynamic",
    ]
    assert service.calls[0][1]["association_id"] == SAVED_DYNAMIC_ID
    assert flask_calls["count"] == 0


def test_delete_returns_no_content_for_the_session_user() -> None:
    client, service, _flask_calls = _client()

    response = client.delete(DETAIL_PATH)

    assert response.status_code == 204
    assert response.content == b""
    assert service.calls == [
        (
            "delete_user_dynamic",
            {
                "principal": PRINCIPAL,
                "country_id": "us",
                "association_id": SAVED_DYNAMIC_ID,
            },
        )
    ]


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (
            AssociationDynamicCountryConflictError("another country's dynamic"),
            400,
            "country",
        ),
        (AssociationDynamicNotFoundError("dynamic was not found"), 404, "not found"),
        (UserDynamicNotFoundError("saved dynamic was not found"), 404, "not found"),
        (
            IntegrityError("statement secret", {}, Exception("credential")),
            409,
            "conflicts",
        ),
        (V2ConfigurationError("postgresql://secret"), 503, "unavailable"),
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

    responses = [
        client.post("/v2/user-dynamics?country_id=us", json=_body()),
        client.get(DETAIL_PATH),
        client.patch(DETAIL_PATH, json={"name": "Renamed"}),
        client.delete(DETAIL_PATH),
    ]

    for response in responses:
        assert response.status_code == status
        assert response.json()["status"] == "error"
        assert message in response.json()["message"].lower()
        assert "secret" not in response.text
        assert "credential" not in response.text


def test_openapi_publishes_the_saved_dynamic_contracts() -> None:
    client, _service, _flask_calls = _client()
    schema = client.get("/v2/openapi.json").json()

    collection = schema["paths"]["/v2/user-dynamics"]["get"]
    parameters = {item["name"]: item for item in collection["parameters"]}
    assert set(parameters) == {"country_id", "offset", "limit", "dynamic_id"}
    assert parameters["limit"]["schema"]["maximum"] == 500
    for path, method in (
        ("/v2/user-dynamics", "post"),
        ("/v2/user-dynamics", "get"),
        ("/v2/user-dynamics/{association_id}", "get"),
        ("/v2/user-dynamics/{association_id}", "patch"),
        ("/v2/user-dynamics/{association_id}", "delete"),
    ):
        operation = schema["paths"][path][method]
        assert {"400", "401", "403", "404", "409", "422", "500", "503"} <= set(
            operation["responses"]
        )

    item_schema = schema["components"]["schemas"]["UserDynamicItem"]
    assert set(item_schema["required"]) == {
        "id",
        "country_id",
        "user_id",
        "dynamic_id",
        "name",
        "description",
        "created_at",
        "updated_at",
    }
    create_ref = schema["paths"]["/v2/user-dynamics"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    create_schema = schema["components"]["schemas"][create_ref.rsplit("/", 1)[-1]]
    assert create_schema["additionalProperties"] is False
    assert set(create_schema["properties"]) == {
        "country_id",
        "dynamic_id",
        "name",
        "description",
    }
    assert set(create_schema["required"]) == {"country_id", "dynamic_id"}
    patch = schema["paths"]["/v2/user-dynamics/{association_id}"]["patch"]
    patch_ref = patch["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    patch_schema = schema["components"]["schemas"][patch_ref.rsplit("/", 1)[-1]]
    assert patch_schema["additionalProperties"] is False
    assert set(patch_schema["properties"]) == {"dynamic_id", "name", "description"}
