"""Shared query-schema and framework-adapter tests."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import Field, ValidationError
import pytest
from werkzeug.datastructures import MultiDict

from policyengine_api.fastapi_routes.query_parameters import query_dependency
from policyengine_api.query_parameters import (
    CountryQuery,
    DuplicateScalarQueryParameterError,
    HouseholdCollectionQuery,
    HouseholdCreateQuery,
    HouseholdDetailQuery,
    PolicyCollectionQuery,
    PolicyCreateQuery,
    ResourceId,
    UserHouseholdCollectionQuery,
    UserHouseholdCreateQuery,
    UserHouseholdDeleteQuery,
    UserHouseholdDetailQuery,
    UserHouseholdUpdateQuery,
    UserPolicyCollectionQuery,
    parse_multidict_query,
    parse_query_items,
)


class ExplicitListQuery(CountryQuery):
    policy_ids: Annotated[
        list[ResourceId],
        Field(default_factory=list, max_length=10),
    ]


def test_canonical_required_defaults_and_normalization() -> None:
    parsed = parse_query_items(PolicyCollectionQuery, [("country_id", "US")])

    assert parsed.country_id == "us"
    assert parsed.offset == 0
    assert parsed.limit == 100
    assert parsed.tax_benefit_model_id is None

    with pytest.raises(ValidationError) as missing:
        parse_query_items(PolicyCollectionQuery, [])
    assert missing.value.errors()[0]["loc"] == ("country_id",)


@pytest.mark.parametrize(
    ("items", "field"),
    [
        ([("country_id", "ca")], "country_id"),
        ([("country_id", "us"), ("offset", "-1")], "offset"),
        ([("country_id", "us"), ("limit", "0")], "limit"),
        ([("country_id", "us"), ("limit", "501")], "limit"),
        (
            [("country_id", "us"), ("tax_benefit_model_id", "not-a-uuid")],
            "tax_benefit_model_id",
        ),
        ([("country_id", "us"), ("unexpected", "value")], "unexpected"),
    ],
)
def test_canonical_malformed_out_of_range_and_unknown_values(
    items: list[tuple[str, str]],
    field: str,
) -> None:
    with pytest.raises(ValidationError) as raised:
        parse_query_items(PolicyCollectionQuery, items)
    assert raised.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("version", ["", " 5.2.0", "v5.2.0", "0.0.0"])
def test_policyengine_version_must_be_canonical(version: str) -> None:
    with pytest.raises(ValidationError):
        parse_query_items(
            PolicyCreateQuery,
            [("country_id", "uk"), ("policyengine_version", version)],
        )

    assert (
        parse_query_items(
            PolicyCreateQuery,
            [("country_id", "uk"), ("policyengine_version", "5.2.0")],
        ).policyengine_version
        == "5.2.0"
    )


def test_duplicate_scalar_is_rejected_and_explicit_list_is_preserved() -> None:
    with pytest.raises(
        DuplicateScalarQueryParameterError,
        match="country_id.*must not be repeated",
    ):
        parse_query_items(
            PolicyCollectionQuery,
            [("country_id", "us"), ("country_id", "uk")],
        )

    first_id = uuid4()
    second_id = uuid4()
    parsed = parse_query_items(
        ExplicitListQuery,
        [
            ("country_id", "us"),
            ("policy_ids", str(first_id)),
            ("policy_ids", str(second_id)),
        ],
    )
    assert parsed.policy_ids == [first_id, second_id]


def test_multidict_adapter_preserves_the_canonical_contract() -> None:
    policy_id = uuid4()
    user_id = uuid4()
    parsed = parse_multidict_query(
        UserPolicyCollectionQuery,
        MultiDict(
            [
                ("country_id", "UK"),
                ("user_id", str(user_id)),
                ("policy_id", str(policy_id)),
                ("offset", "2"),
            ]
        ),
    )

    assert parsed.country_id == "uk"
    assert parsed.user_id == user_id
    assert parsed.policy_id == policy_id
    assert parsed.offset == 2


def _test_client() -> TestClient:
    app = FastAPI()
    dependency = query_dependency(ExplicitListQuery)

    @app.get("/resources")
    def resources(
        query: ExplicitListQuery = Depends(dependency),
    ) -> dict[str, object]:
        return query.model_dump(mode="json")

    return TestClient(app)


def test_fastapi_dependency_rejects_unknown_and_duplicate_scalar_parameters() -> None:
    client = _test_client()

    assert client.get("/resources?country_id=us&unknown=value").status_code == 422
    assert client.get("/resources?country_id=us&country_id=uk").status_code == 422


def test_fastapi_dependency_accepts_repeated_explicit_list_parameters() -> None:
    first_id = uuid4()
    second_id = uuid4()

    response = _test_client().get(
        f"/resources?country_id=US&policy_ids={first_id}&policy_ids={second_id}"
    )

    assert response.status_code == 200
    assert response.json() == {
        "country_id": "us",
        "policy_ids": [str(first_id), str(second_id)],
    }


def test_openapi_matches_composed_runtime_query_contract() -> None:
    operation = _test_client().get("/openapi.json").json()["paths"]["/resources"]["get"]
    parameters = {item["name"]: item for item in operation["parameters"]}

    assert set(parameters) == {"country_id", "policy_ids"}
    assert parameters["country_id"]["required"] is True
    assert parameters["country_id"]["schema"]["enum"] == ["us", "uk"]
    assert parameters["policy_ids"]["required"] is False
    assert parameters["policy_ids"]["schema"]["type"] == "array"
    assert parameters["policy_ids"]["schema"]["maxItems"] == 10
    assert parameters["policy_ids"]["schema"]["items"]["format"] == "uuid"


def test_policy_collection_openapi_defaults_and_bounds() -> None:
    app = FastAPI()
    dependency = query_dependency(PolicyCollectionQuery)

    @app.get("/policies")
    def policies(
        query: PolicyCollectionQuery = Depends(dependency),
    ) -> dict[str, object]:
        return query.model_dump(mode="json")

    operation = TestClient(app).get("/openapi.json").json()["paths"]["/policies"]["get"]
    parameters = {item["name"]: item for item in operation["parameters"]}

    assert parameters["offset"]["schema"] == {
        "type": "integer",
        "minimum": 0,
        "description": "Zero-based result offset",
        "default": 0,
        "title": "Offset",
    }
    assert parameters["limit"]["schema"] == {
        "type": "integer",
        "maximum": 500,
        "minimum": 1,
        "description": "Maximum number of returned resources",
        "default": 100,
        "title": "Limit",
    }
    assert parameters["tax_benefit_model_id"]["required"] is False
    uuid_schema = parameters["tax_benefit_model_id"]["schema"]["anyOf"][0]
    assert uuid_schema == {
        "type": "string",
        "format": "uuid",
        "description": "Exact resource UUID",
    }


def test_uuid_filter_is_materialized_as_uuid() -> None:
    model_id = uuid4()
    parsed = parse_query_items(
        PolicyCollectionQuery,
        [("country_id", "us"), ("tax_benefit_model_id", str(model_id))],
    )
    assert isinstance(parsed.tax_benefit_model_id, UUID)


def test_household_query_contracts_compose_canonical_fields() -> None:
    household_id = uuid4()
    user_id = uuid4()

    collection = parse_query_items(
        HouseholdCollectionQuery,
        [
            ("country_id", "UK"),
            ("default_year", "2026"),
            ("offset", "2"),
            ("limit", "25"),
        ],
    )
    associations = parse_query_items(
        UserHouseholdCollectionQuery,
        [
            ("country_id", "US"),
            ("user_id", str(user_id)),
            ("household_id", str(household_id)),
        ],
    )

    assert collection.model_dump() == {
        "country_id": "uk",
        "offset": 2,
        "limit": 25,
        "default_year": 2026,
    }
    assert associations.country_id == "us"
    assert associations.user_id == user_id
    assert associations.household_id == household_id
    assert associations.offset == 0
    assert associations.limit == 100

    for query_type in (
        HouseholdCreateQuery,
        HouseholdDetailQuery,
        UserHouseholdCreateQuery,
        UserHouseholdDetailQuery,
        UserHouseholdUpdateQuery,
        UserHouseholdDeleteQuery,
    ):
        assert parse_query_items(query_type, [("country_id", "US")]).country_id == (
            "us"
        )


@pytest.mark.parametrize("default_year", ["1899", "2201", "not-a-year"])
def test_household_default_year_is_bounded(default_year: str) -> None:
    with pytest.raises(ValidationError) as raised:
        parse_query_items(
            HouseholdCollectionQuery,
            [("country_id", "us"), ("default_year", default_year)],
        )

    assert raised.value.errors()[0]["loc"] == ("default_year",)


def test_user_household_collection_requires_a_uuid_user() -> None:
    with pytest.raises(ValidationError) as missing:
        parse_query_items(UserHouseholdCollectionQuery, [("country_id", "us")])
    assert missing.value.errors()[0]["loc"] == ("user_id",)

    with pytest.raises(ValidationError) as malformed:
        parse_query_items(
            UserHouseholdCollectionQuery,
            [("country_id", "us"), ("user_id", "not-a-uuid")],
        )
    assert malformed.value.errors()[0]["loc"] == ("user_id",)


@pytest.mark.parametrize(
    "model_type",
    [HouseholdCollectionQuery, UserHouseholdCollectionQuery],
)
def test_household_query_models_reject_unknown_and_duplicate_scalars(
    model_type: type[CountryQuery],
) -> None:
    required = [("country_id", "us")]
    if model_type is UserHouseholdCollectionQuery:
        required.append(("user_id", str(uuid4())))

    with pytest.raises(ValidationError):
        parse_query_items(model_type, [*required, ("unknown", "value")])
    with pytest.raises(DuplicateScalarQueryParameterError):
        parse_query_items(
            model_type,
            [*required, ("country_id", "uk")],
        )


def test_household_collection_openapi_matches_runtime_contract() -> None:
    app = FastAPI()
    dependency = query_dependency(HouseholdCollectionQuery)

    @app.get("/households")
    def households(
        query: HouseholdCollectionQuery = Depends(dependency),
    ) -> dict[str, object]:
        return query.model_dump(mode="json")

    operation = (
        TestClient(app).get("/openapi.json").json()["paths"]["/households"]["get"]
    )
    parameters = {item["name"]: item for item in operation["parameters"]}

    assert set(parameters) == {"country_id", "default_year", "offset", "limit"}
    assert parameters["country_id"]["required"] is True
    assert parameters["default_year"]["required"] is False
    year_schema = parameters["default_year"]["schema"]["anyOf"][0]
    assert year_schema == {
        "type": "integer",
        "maximum": 2200,
        "minimum": 1900,
        "description": "Default year for values without explicit period keys",
    }
    assert parameters["offset"]["schema"]["default"] == 0
    assert parameters["limit"]["schema"]["default"] == 100
