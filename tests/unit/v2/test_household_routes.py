"""Native FastAPI contract tests for immutable v2 households."""

from __future__ import annotations

import string
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlencode
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask, jsonify
from hypothesis import example, given, settings
from hypothesis import strategies as st
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.fastapi_routes.v2.households.response_models import (
    HouseholdDetailResponse,
    HouseholdItem,
)
from policyengine_api.libs.user_auth import UNAUTHENTICATED_USER_HEADER
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.households.types import (
    HouseholdRead,
    NativeHouseholdCreation,
)
from policyengine_api.services.v2.households.validators import (
    HouseholdContentHashCollisionError,
    HouseholdCreationIntegrityError,
    HouseholdNotFoundError,
    HouseholdValidationError,
)

HOUSEHOLD_ID = UUID("00000000-0000-0000-0000-000000000010")
CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _document() -> dict[str, object]:
    memberships = {
        "household": "household-1",
        "family": "family-1",
        "tax_unit": "tax-unit-1",
        "spm_unit": "spm-unit-1",
        "marital_unit": "marital-unit-1",
    }
    document: dict[str, object] = {
        "people": [
            {
                "id": "person-1",
                "source_name": "you",
                "values": {"age": {"2026": 40}},
                "memberships": memberships,
            }
        ]
    }
    for collection, identifier in memberships.items():
        document[collection] = [
            {"id": identifier, "source_name": "primary", "values": {}}
        ]
    return document


def _household_read(
    *,
    household_id: UUID = HOUSEHOLD_ID,
    country_id: str = "us",
) -> HouseholdRead:
    return HouseholdRead(
        id=household_id,
        country_id=country_id,
        default_year=2026,
        household_data=_document(),
        created_at=CREATED_AT,
        updated_at=CREATED_AT + timedelta(seconds=1),
    )


class FakeHouseholdService:
    def __init__(self) -> None:
        self.created = True
        self.error: Exception | None = None
        self.calls: list[tuple[str, object]] = []

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    def create_household(self, household_input) -> NativeHouseholdCreation:
        self.calls.append(("create_household", household_input))
        self._raise()
        return NativeHouseholdCreation(item=_household_read(), created=self.created)

    def get_household(self, **filters) -> HouseholdRead:
        self.calls.append(("get_household", filters))
        self._raise()
        return _household_read(household_id=filters["household_id"])


def _client(
    service: FakeHouseholdService,
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
        specification_provider=dict,
        v2_household_service_factory=lambda: service,
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


def _body(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "country_id": "us",
        "default_year": 2026,
        "household_data": _document(),
    }
    body.update(changes)
    return body


def test_create_returns_201_for_new_and_200_for_deduplicated_content() -> None:
    service = FakeHouseholdService()
    client, flask_calls = _client(service)

    created = client.post("/v2/households?country_id=US", json=_body())
    service.created = False
    deduplicated = client.post("/v2/households?country_id=us", json=_body())

    assert created.status_code == 201
    assert deduplicated.status_code == 200
    assert created.json() == deduplicated.json()
    assert created.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "item": {
                "id": str(HOUSEHOLD_ID),
                "country_id": "us",
                "default_year": 2026,
                "household_data": _document(),
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:01Z",
            }
        },
    }
    command = service.calls[0][1]
    assert command.country_id == "us"
    assert command.default_year == 2026
    assert flask_calls["count"] == 0


def test_create_rejects_country_mismatch_and_non_content_fields() -> None:
    service = FakeHouseholdService()
    client, _flask_calls = _client(service)

    mismatch = client.post("/v2/households?country_id=uk", json=_body())
    named = client.post(
        "/v2/households?country_id=us",
        json={**_body(), "name": "Not base content", "description": "No"},
    )
    modeled = client.post(
        "/v2/households?country_id=us",
        json={**_body(), "tax_benefit_model_version_id": str(uuid4())},
    )

    assert mismatch.status_code == 400
    assert named.status_code == 422
    assert modeled.status_code == 422
    assert service.calls == []


@pytest.mark.parametrize("default_year", [None, 1899, 2201])
def test_create_requires_a_bounded_non_null_default_year(default_year) -> None:
    service = FakeHouseholdService()
    client, _flask_calls = _client(service)

    response = client.post(
        "/v2/households?country_id=us",
        json=_body(default_year=default_year),
    )

    assert response.status_code == 422
    assert service.calls == []


def test_create_rejects_unknown_duplicate_oversized_and_excessive_entities() -> None:
    service = FakeHouseholdService()
    client, _flask_calls = _client(service)

    unknown = client.post("/v2/households?country_id=us&search=age", json=_body())
    duplicate = client.post("/v2/households?country_id=us&country_id=uk", json=_body())
    excessive_document = _document()
    excessive_document["people"] = [
        {
            "id": f"person-{index}",
            "values": {},
            "memberships": {},
        }
        for index in range(1_001)
    ]
    excessive = client.post(
        "/v2/households?country_id=us",
        json=_body(household_data=excessive_document),
    )
    oversized = client.post(
        "/v2/households?country_id=us",
        content=b'{"country_id":"us","padding":"' + b"x" * 1_048_576 + b'"}',
        headers={"content-type": "application/json"},
    )

    assert unknown.status_code == 422
    assert duplicate.status_code == 422
    assert excessive.status_code == 422
    assert oversized.status_code == 413
    assert oversized.json()["status"] == "error"
    assert service.calls == []


def test_detail_is_country_scoped_and_returns_complete_content() -> None:
    service = FakeHouseholdService()
    client, flask_calls = _client(service)

    response = client.get(f"/v2/households/{HOUSEHOLD_ID}?country_id=US")
    service.error = HouseholdNotFoundError("household was not found")
    missing = client.get(f"/v2/households/{uuid4()}?country_id=uk")

    assert response.status_code == 200
    assert response.json()["result"]["item"]["household_data"] == _document()
    assert service.calls[0] == (
        "get_household",
        {"country_id": "us", "household_id": HOUSEHOLD_ID},
    )
    assert missing.status_code == 404
    assert missing.json() == {"status": "error", "message": "household was not found"}
    assert flask_calls["count"] == 0


class HouseholdListingService(FakeHouseholdService):
    """A service that would return stored households to any route that asked."""

    def list_households(self, **filters) -> SimpleNamespace:
        self.calls.append(("list_households", filters))
        return SimpleNamespace(
            items=(_household_read(),),
            offset=filters["offset"],
            limit=filters["limit"],
            has_more=True,
        )


def test_anonymous_household_collection_is_not_served() -> None:
    service = HouseholdListingService()
    client, flask_calls = _client(service)

    response = client.get("/v2/households?country_id=us&offset=0&limit=500")

    assert response.status_code == 404
    assert response.json() == {
        "status": "error",
        "message": "API v2 resource 'households' was not found",
    }
    assert service.calls == []
    assert flask_calls["count"] == 0


_COLLECTION_PATHS = ("/v2/households", "/v2/households/", "/v2/%68ouseholds")
_QUERY_TEXT = st.text(alphabet=string.printable, max_size=12)


@st.composite
def _collection_queries(draw: st.DrawFn) -> list[tuple[str, str]]:
    country = draw(st.none() | st.sampled_from(["us", "uk", "US", "Uk"]) | _QUERY_TEXT)
    offset = draw(st.none() | st.integers(min_value=-5, max_value=10**6))
    limit = draw(st.none() | st.integers(min_value=-5, max_value=1_000))
    default_year = draw(st.none() | st.integers(min_value=1_800, max_value=2_300))
    pairs = [
        (name, str(value))
        for name, value in (
            ("country_id", country),
            ("offset", offset),
            ("limit", limit),
            ("default_year", default_year),
        )
        if value is not None
    ]
    extras = st.tuples(
        st.sampled_from(["search", "user_id", "household_id", "page", "country_id"])
        | st.text(alphabet=string.ascii_lowercase + "_", min_size=1, max_size=12),
        _QUERY_TEXT,
    )
    pairs.extend(draw(st.lists(extras, max_size=3)))
    return draw(st.permutations(pairs))


_BEARER_TOKENS = st.text(
    alphabet=string.ascii_letters + string.digits + "-_.", min_size=1, max_size=64
)
_CREDENTIAL_HEADERS = st.one_of(
    st.just({}),
    _BEARER_TOKENS.map(lambda token: {"Authorization": f"Bearer {token}"}),
    st.uuids().map(lambda user: {UNAUTHENTICATED_USER_HEADER: str(user)}),
    st.tuples(_BEARER_TOKENS, st.uuids()).map(
        lambda pair: {
            "Authorization": f"Bearer {pair[0]}",
            UNAUTHENTICATED_USER_HEADER: str(pair[1]),
        }
    ),
    st.uuids().map(
        lambda user: {
            "Origin": "https://policyengine.org",
            UNAUTHENTICATED_USER_HEADER: str(user),
        }
    ),
)


def test_household_collection_path_never_returns_household_content() -> None:
    """No query or credential on the collection path returns stored households.

    The backing service would return a page to any route that asked, so the
    property holds only if no collection route exists to ask it.
    """
    service = HouseholdListingService()
    client, flask_calls = _client(service)

    @settings(max_examples=150, deadline=None)
    @given(
        path=st.sampled_from(_COLLECTION_PATHS),
        query=_collection_queries(),
        headers=_CREDENTIAL_HEADERS,
    )
    @example(path="/v2/households", query=[("country_id", "us")], headers={})
    @example(
        path="/v2/households",
        query=[("country_id", "uk"), ("offset", "500"), ("limit", "500")],
        headers={"Authorization": "Bearer anything"},
    )
    @example(
        path="/v2/households",
        query=[("country_id", "us"), ("default_year", "2026")],
        headers={UNAUTHENTICATED_USER_HEADER: str(uuid4())},
    )
    def check(path: str, query: list[tuple[str, str]], headers: dict[str, str]) -> None:
        service.calls.clear()
        response = client.get(f"{path}?{urlencode(query)}", headers=headers)

        assert service.calls == []
        assert "household_data" not in response.text
        assert str(HOUSEHOLD_ID) not in response.text
        assert "result" not in response.json()
        assert flask_calls["count"] == 0
        assert response.json()["status"] == "error"
        assert response.status_code in {401, 404, 405}

    check()


# The signed-out header carries a UUID the caller generates, so it proves no
# identity: an operation that accepts it alone is as open as one without security.
_SELF_ASSERTED_SCHEMES = frozenset({"UnauthenticatedUser"})
_HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)
_ELEMENT_KEYWORDS = (
    "items",
    "prefixItems",
    "additionalProperties",
    "patternProperties",
)


def _referenced_schemas(node: object, components: dict[str, object]) -> set[str]:
    """Return the name of every component schema reachable from an OpenAPI node."""
    names: set[str] = set()
    pending = [node]
    while pending:
        current = pending.pop()
        if isinstance(current, list):
            pending.extend(current)
        elif isinstance(current, dict):
            reference = current.get("$ref")
            if isinstance(reference, str):
                name = reference.rsplit("/", 1)[-1]
                if name not in names:
                    names.add(name)
                    pending.append(components[name])
            pending.extend(value for key, value in current.items() if key != "$ref")
    return names


def _holds_many_households(node: object, components: dict[str, object]) -> bool:
    """Whether a schema has an array or map whose elements can hold a HouseholdItem.

    Element schemas are followed through references and composition
    (``anyOf``, ``allOf``, nested models), so ``list[HouseholdItem | None]``
    and ``list[Wrapper]`` count as well as ``list[HouseholdItem]``.
    """
    pending = [node]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if isinstance(current, list):
            pending.extend(current)
            continue
        if not isinstance(current, dict):
            continue
        for keyword in _ELEMENT_KEYWORDS:
            element = current.get(keyword)
            if isinstance(element, dict | list) and "HouseholdItem" in (
                _referenced_schemas(element, components)
            ):
                return True
        reference = current.get("$ref")
        if isinstance(reference, str):
            name = reference.rsplit("/", 1)[-1]
            if name not in visited:
                visited.add(name)
                pending.append(components[name])
        pending.extend(value for key, value in current.items() if key != "$ref")
    return False


def _reachable_without_account(
    operation: dict[str, object], schema: dict[str, object]
) -> bool:
    """Whether a security alternative needs nothing beyond the signed-out header."""
    security = operation.get("security", schema.get("security")) or []
    return not security or any(
        set(alternative) <= _SELF_ASSERTED_SCHEMES for alternative in security
    )


def _open_household_collections(schema: dict[str, object]) -> set[tuple[str, str]]:
    """Return operations that return many households to a caller with no account.

    A route that returned only the caller's own households in full would also
    match; it would need an explicit, reviewed exception here.
    """
    components = schema.get("components", {}).get("schemas", {})
    return {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method, operation in operations.items()
        if method in _HTTP_METHODS
        and _reachable_without_account(operation, schema)
        and any(
            _holds_many_households(response, components)
            for status, response in operation.get("responses", {}).items()
            if str(status).startswith("2")
        )
    }


class _WrappedHousehold(BaseModel):
    household: HouseholdItem


def test_open_household_collection_check_catches_each_list_and_credential_shape() -> (
    None
):
    app = FastAPI()
    signed_out = [{"UnauthenticatedUser": []}]
    shapes = {
        "/list": (list[HouseholdItem], None),
        "/optional-items": (list[HouseholdItem | None], None),
        "/map": (dict[str, HouseholdItem], None),
        "/wrapped": (list[_WrappedHousehold], None),
        "/signed-out-header": (list[HouseholdItem], signed_out),
        "/token-or-header": (
            list[HouseholdItem],
            [{"UserAccessToken": []}, *signed_out],
        ),
        "/optional-token": (list[HouseholdItem], [{}, {"UserAccessToken": []}]),
        "/token-only": (list[HouseholdItem], [{"UserAccessToken": []}]),
        "/one-household": (HouseholdDetailResponse, None),
    }
    for path, (response_model, security) in shapes.items():
        app.add_api_route(
            path,
            lambda: None,
            methods=["GET"],
            response_model=response_model,
            openapi_extra=None if security is None else {"security": security},
        )

    assert _open_household_collections(app.openapi()) == {
        ("GET", "/list"),
        ("GET", "/optional-items"),
        ("GET", "/map"),
        ("GET", "/wrapped"),
        ("GET", "/signed-out-header"),
        ("GET", "/token-or-header"),
        ("GET", "/optional-token"),
    }


def test_no_open_v2_operation_returns_many_households() -> None:
    service = FakeHouseholdService()
    client, _flask_calls = _client(service)
    schema = client.get("/v2/openapi.json").json()

    assert _open_household_collections(schema) == set()
    assert set(schema["paths"]["/v2/households"]) == {"post"}


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (HouseholdValidationError("invalid relationship"), 400, "relationship"),
        (HouseholdNotFoundError("absent household"), 404, "absent"),
        (
            HouseholdContentHashCollisionError("database statement secret"),
            409,
            "conflicts",
        ),
        (
            HouseholdCreationIntegrityError("database statement secret"),
            500,
            "integrity",
        ),
        (V2ConfigurationError("postgresql://secret"), 503, "unavailable"),
        (
            OperationalError("statement secret", {}, Exception("credential")),
            503,
            "unavailable",
        ),
        (PoolTimeoutError("pool timeout"), 503, "unavailable"),
        (RuntimeError("credential and household value"), 500, "operation failed"),
    ],
)
def test_household_failures_map_to_secret_safe_typed_errors(
    error: Exception,
    status: int,
    message: str,
) -> None:
    service = FakeHouseholdService()
    service.error = error
    client, _flask_calls = _client(service)

    response = client.get(f"/v2/households/{HOUSEHOLD_ID}?country_id=us")

    assert response.status_code == status
    assert response.json()["status"] == "error"
    assert message in response.json()["message"].lower()
    assert "secret" not in response.text
    assert "credential" not in response.text


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_base_household_mutations_are_not_exposed(method: str) -> None:
    service = FakeHouseholdService()
    client, flask_calls = _client(service)

    response = client.request(
        method.upper(),
        f"/v2/households/{HOUSEHOLD_ID}?country_id=us",
        json={},
    )

    assert response.status_code == 405
    assert response.json()["status"] == "error"
    assert service.calls == []
    assert flask_calls["count"] == 0


def test_openapi_publishes_query_body_item_and_error_schemas() -> None:
    service = FakeHouseholdService()
    client, _flask_calls = _client(service)
    schema = client.get("/v2/openapi.json").json()

    assert {path for path in schema["paths"] if path.startswith("/v2/households")} == {
        "/v2/households",
        "/v2/households/{household_id}",
    }
    detail = schema["paths"]["/v2/households/{household_id}"]["get"]
    parameters = {item["name"]: item for item in detail["parameters"]}
    assert set(parameters) == {"household_id", "country_id"}
    assert parameters["household_id"]["schema"]["format"] == "uuid"
    assert parameters["country_id"]["required"] is True

    create = schema["paths"]["/v2/households"]["post"]
    assert {"200", "201", "400", "404", "409", "413", "422", "500", "503"} <= set(
        create["responses"]
    )
    request_ref = create["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    request_schema = schema["components"]["schemas"][request_ref.rsplit("/", 1)[-1]]
    assert request_schema["additionalProperties"] is False
    assert request_schema["properties"]["default_year"]["minimum"] == 1900
    document_refs = request_schema["properties"]["household_data"]["anyOf"]
    us_document = next(
        schema["components"]["schemas"][item["$ref"].rsplit("/", 1)[-1]]
        for item in document_refs
        if item["$ref"].rsplit("/", 1)[-1].startswith("USHouseholdDocument")
    )
    spm_schema = us_document["properties"]["spm"]
    assert spm_schema["$ref"].endswith("/SPMSelection")
    assert "default" not in spm_schema
    assert "anyOf" not in spm_schema
    assert "spm" not in us_document["required"]
    assert us_document["properties"]["people"]["maxItems"] == 1000
    entity_record = schema["components"]["schemas"]["HouseholdEntityRecord"]
    assert entity_record["properties"]["values"]["maxProperties"] == 500
    item_schema = schema["components"]["schemas"]["HouseholdItem"]
    assert set(item_schema["required"]) == {
        "id",
        "country_id",
        "default_year",
        "household_data",
        "created_at",
        "updated_at",
    }
    assert {
        "content_hash",
        "canonicalization_version",
        "name",
        "description",
    }.isdisjoint(item_schema["properties"])


def test_browser_preflight_and_cross_origin_errors_use_application_cors() -> None:
    service = FakeHouseholdService()
    client, _flask_calls = _client(service)
    origin = "https://app.example"

    preflight = client.options(
        "/v2/households",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    error = client.post(
        "/v2/households?country_id=us&search=age",
        json=_body(),
        headers={"Origin": origin},
    )

    assert preflight.status_code == 200
    assert "POST" in preflight.headers["access-control-allow-methods"]
    assert service.calls == []
    assert error.status_code == 422
    assert error.headers["access-control-allow-origin"] == origin
    assert (
        "x-policyengine-request-id"
        in error.headers["access-control-expose-headers"].lower()
    )


def test_native_household_routes_do_not_use_cloud_sql_or_flask(monkeypatch) -> None:
    def reject_cloud_sql():
        msg = "Cloud SQL must not be selected"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "policyengine_api.data.orm.get_v1_session_factory",
        reject_cloud_sql,
    )
    service = FakeHouseholdService()
    client, flask_calls = _client(service)

    assert client.get(f"/v2/households/{HOUSEHOLD_ID}?country_id=us").status_code == 200
    assert service.calls[0][0] == "get_household"
    assert flask_calls["count"] == 0


@pytest.mark.parametrize(
    "selection",
    [
        None,
        {"geography_kind": "national"},
        {
            "forecast_content_sha256": "a" * 64,
            "scenario": "baseline",
            "geography_kind": "national",
            "geography_id": None,
            "county_vintage": "2020",
            "as_of": None,
        },
    ],
)
def test_native_household_http_preserves_spm_and_historical_omission(
    monkeypatch, selection
) -> None:
    from copy import deepcopy

    service = FakeHouseholdService()
    saved = _household_read()
    if selection is not None:
        saved.household_data["spm"] = deepcopy(selection)
    monkeypatch.setattr(service, "get_household", lambda **_filters: saved)
    client, _ = _client(service)
    response = client.get(f"/v2/households/{HOUSEHOLD_ID}?country_id=us")
    assert response.status_code == 200
    returned = response.json()["result"]["item"]["household_data"]
    if selection is None:
        assert "spm" not in returned
    else:
        assert returned["spm"] == selection

    created = client.post(
        "/v2/households?country_id=us",
        json={
            "country_id": "us",
            "default_year": 2026,
            "household_data": returned,
        },
    )
    assert created.status_code == 201
    supplied = service.calls[-1][1].household_data
    if selection is None:
        assert "spm" not in supplied
    else:
        assert supplied["spm"] == selection


@pytest.mark.parametrize(
    "selection", [None, [], {"unexpected": True}, {"geography_kind": "metro"}]
)
def test_native_household_invalid_spm_is_rejected_before_service(selection) -> None:
    service = FakeHouseholdService()
    client, _ = _client(service)
    document = _document()
    document["spm"] = selection
    response = client.post(
        "/v2/households?country_id=us",
        json={
            "country_id": "us",
            "default_year": 2026,
            "household_data": document,
        },
    )
    assert response.status_code == 422
    assert service.calls == []
