"""Typed route coverage for the dynamic parameter category (C1 · 51).

The routes serve dynamic parameters and their current-law values apart from
policy parameters: ``/v2/dynamic-parameters`` (with ``/{parameter_id}`` and
``/children``), ``/v2/dynamic-parameter-values`` (with ``/{value_id}``) and
``/v2/model-catalog/dynamic-parameters``. Each forwards its query to the
metadata service's ``dynamic_parameters`` reads.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from policyengine_api.services.v2.metadata.dynamic_parameters.types import (
    DynamicParameterTreeLevel,
)

from policyengine_api.services.v2.metadata.types import (
    ParameterFilter,
    ParameterValueFilter,
)
from policyengine_api.services.v2.metadata.validators import (
    MetadataResourceNotFoundError,
)
from tests.fixtures.v2_metadata_routes import (
    ResourceReader,
    metadata_route_client,
    resource_results,
)

SUMMARY_FIELDS = {
    "id",
    "name",
    "label",
    "description",
    "data_type",
    "unit",
    "economy",
    "household",
}


def _openapi_schema() -> dict:
    results, _ids = resource_results()
    return (
        metadata_route_client(lambda: ResourceReader(results))
        .get("/v2/openapi.json")
        .json()
    )


def _query_parameters(schema: dict, path: str) -> dict[str, dict]:
    return {
        parameter["name"]: parameter
        for parameter in schema["paths"][path]["get"]["parameters"]
        if parameter["in"] == "query"
    }


def test_each_dynamic_parameter_route_returns_its_typed_result() -> None:
    results, ids = resource_results()
    reader = ResourceReader(results)
    client = metadata_route_client(lambda: reader)
    requests = [
        ("list_dynamic_parameters", "/v2/dynamic-parameters?country_id=us"),
        (
            "list_dynamic_parameter_children",
            "/v2/dynamic-parameters/children?country_id=us",
        ),
        (
            "get_dynamic_parameter",
            f"/v2/dynamic-parameters/{ids['dynamic_parameter_id']}?country_id=us",
        ),
        ("list_dynamic_parameter_values", "/v2/dynamic-parameter-values?country_id=us"),
        (
            "get_dynamic_parameter_value",
            f"/v2/dynamic-parameter-values/{ids['dynamic_parameter_value_id']}"
            "?country_id=us",
        ),
        (
            "get_catalog_dynamic_parameters",
            "/v2/model-catalog/dynamic-parameters?country_id=us",
        ),
    ]

    for expected_method, path in requests:
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["message"] is None
        assert payload["result"]["policyengine_version"] == "4.20.3"
        assert reader.calls[-1][0] == expected_method

    assert reader.closed


def test_the_dynamic_parameter_collection_forwards_its_filters_and_page() -> None:
    results, _ids = resource_results()
    reader = ResourceReader(results)

    response = metadata_route_client(lambda: reader).get(
        "/v2/dynamic-parameters"
        "?country_id=uk&policyengine_version=4.19.0&offset=5&limit=10"
        "&search=labour&name=gov.dynamic.obr_labour_supply_assumptions"
        "&name=gov.simulation.labour_supply_responses.income_elasticity"
    )

    assert response.status_code == 200
    assert reader.calls == [
        (
            "list_dynamic_parameters",
            ("uk", "4.19.0"),
            {
                "offset": 5,
                "limit": 10,
                "parameter_filter": ParameterFilter(
                    search="labour",
                    names=(
                        "gov.dynamic.obr_labour_supply_assumptions",
                        "gov.simulation.labour_supply_responses.income_elasticity",
                    ),
                ),
            },
        )
    ]


def test_dynamic_parameter_items_carry_no_settable_field() -> None:
    results, ids = resource_results()
    client = metadata_route_client(lambda: ResourceReader(results))

    page = client.get("/v2/dynamic-parameters?country_id=us").json()["result"]
    detail = client.get(
        f"/v2/dynamic-parameters/{ids['dynamic_parameter_id']}?country_id=us"
    ).json()["result"]
    children = client.get("/v2/dynamic-parameters/children?country_id=us").json()[
        "result"
    ]

    assert set(page["items"][0]) == SUMMARY_FIELDS
    assert set(detail["item"]) == SUMMARY_FIELDS
    assert set(children["items"][0]["parameter"]) == SUMMARY_FIELDS


def test_the_children_route_forwards_its_level_and_page() -> None:
    results, _ids = resource_results()
    reader = ResourceReader(results)

    response = metadata_route_client(lambda: reader).get(
        "/v2/dynamic-parameters/children"
        "?country_id=us&parent_path=simulation&settable=true&offset=2&limit=50"
    )

    assert response.status_code == 200
    assert reader.calls == [
        (
            "list_dynamic_parameter_children",
            ("us", None),
            {
                "level": DynamicParameterTreeLevel(
                    parent_path="simulation", settable=True
                ),
                "offset": 2,
                "limit": 50,
            },
        )
    ]


def test_the_children_route_defaults_to_every_child_of_the_top_level() -> None:
    results, _ids = resource_results()
    reader = ResourceReader(results)

    response = metadata_route_client(lambda: reader).get(
        "/v2/dynamic-parameters/children?country_id=us"
    )

    assert response.status_code == 200
    assert reader.calls == [
        (
            "list_dynamic_parameter_children",
            ("us", None),
            {"level": DynamicParameterTreeLevel(), "offset": 0, "limit": 100},
        )
    ]
    assert DynamicParameterTreeLevel() == DynamicParameterTreeLevel(
        parent_path="", settable=False
    )


@pytest.mark.parametrize(
    "query",
    [
        "country_id=us&reform_changeable=true",
        "country_id=us&settable=sometimes",
        "country_id=us&settable=true&settable=true",
        "country_id=us&parent_path=" + "a" * 513,
        "country_id=us&parent_path=gov&parent_path=simulation",
    ],
)
def test_the_children_route_rejects_invalid_levels_before_reading(query: str) -> None:
    calls = []

    def factory():
        calls.append("called")
        results, _ids = resource_results()
        return ResourceReader(results)

    response = metadata_route_client(factory).get(
        f"/v2/dynamic-parameters/children?{query}"
    )

    assert response.status_code == 422, response.text
    assert calls == []


def test_the_value_listing_forwards_its_filters_with_the_request_instant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from policyengine_api.fastapi_routes.v2.metadata import route_support

    request_instant = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(route_support, "utc_now", lambda: request_instant)
    results, ids = resource_results()
    reader = ResourceReader(results)

    response = metadata_route_client(lambda: reader).get(
        "/v2/dynamic-parameter-values",
        params={
            "country_id": "us",
            "policyengine_version": "4.19.0",
            "parameter_id": str(ids["dynamic_parameter_id"]),
            "parameter_name": "simulation.marginal_tax_rate_delta",
            "current": "true",
            "offset": 5,
            "limit": 7,
        },
    )

    assert response.status_code == 200
    assert reader.calls == [
        (
            "list_dynamic_parameter_values",
            ("us", "4.19.0"),
            {
                "value_filter": ParameterValueFilter(
                    parameter_id=ids["dynamic_parameter_id"],
                    current=True,
                    now=request_instant,
                    parameter_names=("simulation.marginal_tax_rate_delta",),
                ),
                "offset": 5,
                "limit": 7,
            },
        )
    ]
    # Values in effect today are reused only until the next UTC midnight.
    assert response.headers["cache-control"] == "public, max-age=43200"


def test_the_detail_routes_forward_their_ids_and_version() -> None:
    results, ids = resource_results()
    reader = ResourceReader(results)
    client = metadata_route_client(lambda: reader)

    client.get(f"/v2/dynamic-parameters/{ids['dynamic_parameter_id']}?country_id=us")
    client.get(
        f"/v2/dynamic-parameter-values/{ids['dynamic_parameter_value_id']}"
        "?country_id=uk&policyengine_version=4.20.3"
    )

    assert reader.calls == [
        ("get_dynamic_parameter", ("us", ids["dynamic_parameter_id"], None), {}),
        (
            "get_dynamic_parameter_value",
            ("uk", ids["dynamic_parameter_value_id"], "4.20.3"),
            {},
        ),
    ]


def test_an_id_the_category_lacks_answers_404() -> None:
    results, ids = resource_results()
    reader = ResourceReader(
        results,
        error=MetadataResourceNotFoundError(
            f"dynamic parameter {ids['parameter_id']} was not found"
        ),
    )

    response = metadata_route_client(lambda: reader).get(
        f"/v2/dynamic-parameters/{ids['parameter_id']}?country_id=us"
    )

    assert response.status_code == 404
    assert response.json() == {
        "status": "error",
        "message": f"dynamic parameter {ids['parameter_id']} was not found",
    }
    assert reader.closed


def test_the_catalog_route_serves_the_whole_category_in_one_response() -> None:
    results, ids = resource_results()
    reader = ResourceReader(results)

    response = metadata_route_client(lambda: reader).get(
        "/v2/model-catalog/dynamic-parameters?country_id=us&policyengine_version=4.20.3"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=86400"
    result = response.json()["result"]
    assert set(result) == {
        "policyengine_version",
        "catalog_format",
        "parameters",
        "node_labels",
    }
    parameter = result["parameters"][0]
    assert set(parameter) == SUMMARY_FIELDS | {"values"}
    assert parameter["id"] == str(ids["dynamic_parameter_id"])
    assert parameter["values"] == [
        {"start_date": "2025-01-01T00:00:00Z", "end_date": None, "value": 1000}
    ]
    assert result["node_labels"] == {"simulation": None}
    assert reader.calls == [("get_catalog_dynamic_parameters", ("us", "4.20.3"), {})]


@pytest.mark.parametrize(
    "query",
    [
        "country_id=us&name=simulation.marginal_tax_rate_delta",
        "country_id=us&offset=0",
        "country_id=us&settable=true",
    ],
)
def test_the_catalog_route_takes_no_names_pages_or_filters(query: str) -> None:
    calls = []

    def factory():
        calls.append("called")
        results, _ids = resource_results()
        return ResourceReader(results)

    response = metadata_route_client(factory).get(
        f"/v2/model-catalog/dynamic-parameters?{query}"
    )

    assert response.status_code == 422
    assert calls == []


def test_openapi_declares_each_dynamic_parameter_query() -> None:
    schema = _openapi_schema()

    children = _query_parameters(schema, "/v2/dynamic-parameters/children")
    assert set(children) == {
        "country_id",
        "policyengine_version",
        "offset",
        "limit",
        "parent_path",
        "settable",
    }
    assert children["settable"]["required"] is False
    assert children["settable"]["schema"]["type"] == "boolean"
    assert children["settable"]["schema"]["default"] is False
    assert children["parent_path"]["schema"]["maxLength"] == 512
    assert set(_query_parameters(schema, "/v2/dynamic-parameters")) == set(
        _query_parameters(schema, "/v2/parameters")
    )
    assert set(_query_parameters(schema, "/v2/dynamic-parameter-values")) == set(
        _query_parameters(schema, "/v2/parameter-values")
    )
    for path in (
        "/v2/dynamic-parameters/{parameter_id}",
        "/v2/dynamic-parameter-values/{value_id}",
        "/v2/model-catalog/dynamic-parameters",
    ):
        assert set(_query_parameters(schema, path)) == {
            "country_id",
            "policyengine_version",
        }, path


def test_the_policy_children_query_keeps_its_contract() -> None:
    schema = _openapi_schema()

    children = _query_parameters(schema, "/v2/parameters/children")

    assert set(children) == {
        "country_id",
        "policyengine_version",
        "offset",
        "limit",
        "parent_path",
        "reform_changeable",
    }
    assert children["parent_path"]["schema"]["maxLength"] == 512
    assert children["parent_path"]["schema"]["default"] == ""
    assert children["reform_changeable"]["schema"]["default"] is False


def test_openapi_documents_the_pruned_version_answers() -> None:
    schema = _openapi_schema()

    for path in (
        "/v2/dynamic-parameters/children",
        "/v2/dynamic-parameter-values",
        "/v2/dynamic-parameter-values/{value_id}",
        "/v2/model-catalog/dynamic-parameters",
    ):
        responses = schema["paths"][path]["get"]["responses"]
        assert "pruned" in responses["404"]["description"], path
        assert "pruning" in responses["503"]["description"], path
    for path in ("/v2/dynamic-parameters", "/v2/dynamic-parameters/{parameter_id}"):
        responses = schema["paths"][path]["get"]["responses"]
        assert "pruned" not in responses["404"]["description"], path


def test_openapi_names_each_dynamic_parameter_response_schema() -> None:
    schema = _openapi_schema()

    expected = {
        "/v2/dynamic-parameters": "MetadataDynamicParameterPageResponse",
        "/v2/dynamic-parameters/{parameter_id}": (
            "MetadataDynamicParameterDetailResponse"
        ),
        "/v2/dynamic-parameters/children": "MetadataDynamicParameterChildPageResponse",
        "/v2/dynamic-parameter-values": "MetadataDynamicParameterValuePageResponse",
        "/v2/dynamic-parameter-values/{value_id}": (
            "MetadataDynamicParameterValueDetailResponse"
        ),
        "/v2/model-catalog/dynamic-parameters": (
            "MetadataCatalogDynamicParametersResponse"
        ),
    }
    for path, schema_name in expected.items():
        success = schema["paths"][path]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert success["$ref"] == f"#/components/schemas/{schema_name}", path
