"""Route coverage for the stored parameter tree at /v2/parameters/children."""

from __future__ import annotations

import pytest

from policyengine_api.services.v2.metadata.types import (
    ParameterTreeLevel,
)
from policyengine_api.services.v2.metadata.validators import (
    ParameterTreeUnavailableError,
)
from tests.fixtures.v2_metadata_routes import (
    ResourceReader,
    metadata_route_client,
    resource_results,
    vary_values,
)


def test_parameter_children_route_forwards_its_level_and_page() -> None:
    results, _ids = resource_results()
    reader = ResourceReader(results)

    response = metadata_route_client(lambda: reader).get(
        "/v2/parameters/children",
        params={
            "country_id": "UK",
            "policyengine_version": "4.19.0",
            "parent_path": "gov.hmrc.income_tax.rates.uk",
            "reform_changeable": "true",
            "offset": 10,
            "limit": 20,
        },
    )

    assert response.status_code == 200
    assert reader.calls == [
        (
            "list_parameter_children",
            ("uk", "4.19.0"),
            {
                "level": ParameterTreeLevel(
                    parent_path="gov.hmrc.income_tax.rates.uk",
                    reform_changeable=True,
                ),
                "offset": 10,
                "limit": 20,
            },
        )
    ]


def test_parameter_children_route_defaults_to_the_full_top_level() -> None:
    results, _ids = resource_results()
    reader = ResourceReader(results)

    response = metadata_route_client(lambda: reader).get(
        "/v2/parameters/children", params={"country_id": "us"}
    )

    assert response.status_code == 200
    assert reader.calls == [
        (
            "list_parameter_children",
            ("us", None),
            {"level": ParameterTreeLevel(), "offset": 0, "limit": 100},
        )
    ]


@pytest.mark.parametrize(
    "query",
    [
        "country_id=us&parentpath=gov",
        "country_id=us&parent_path=gov&parent_path=gov.irs",
        "country_id=us&reform_changeable=yes-please",
        "country_id=us&limit=501",
        "country_id=ca",
        "parent_path=gov",
        "country_id=us&parent_path=" + "x" * 513,
    ],
)
def test_parameter_children_route_rejects_invalid_queries(query: str) -> None:
    calls = []

    def factory():
        calls.append("called")
        results, _ids = resource_results()
        return ResourceReader(results)

    response = metadata_route_client(factory).get(f"/v2/parameters/children?{query}")

    assert response.status_code == 422
    assert response.json() == {
        "status": "error",
        "message": "Invalid API v2 request",
    }
    assert calls == []


def test_parameter_children_route_reports_an_unwritten_tree_as_unavailable() -> None:
    results, _ids = resource_results()
    message = (
        "catalog version 6.7.5 has no parameter tree: catalog publication writes "
        "trees only for the versions it publishes and for the installed version "
        "with catalog format 2"
    )
    reader = ResourceReader(results, error=ParameterTreeUnavailableError(message))

    response = metadata_route_client(lambda: reader).get(
        "/v2/parameters/children", params={"country_id": "us"}
    )

    assert response.status_code == 503
    assert response.json() == {"status": "error", "message": message}


def test_parameter_children_openapi_declares_the_query_contract() -> None:
    results, _ids = resource_results()
    schema = (
        metadata_route_client(lambda: ResourceReader(results))
        .get("/v2/openapi.json")
        .json()
    )

    parameters = {
        parameter["name"]: parameter
        for parameter in schema["paths"]["/v2/parameters/children"]["get"]["parameters"]
    }

    assert set(parameters) == {
        "country_id",
        "policyengine_version",
        "offset",
        "limit",
        "parent_path",
        "reform_changeable",
    }
    assert parameters["country_id"]["required"] is True
    assert parameters["parent_path"]["schema"]["default"] == ""
    assert parameters["parent_path"]["schema"]["maxLength"] == 512
    assert parameters["reform_changeable"]["schema"]["type"] == "boolean"
    assert parameters["reform_changeable"]["schema"]["default"] is False
    assert parameters["limit"]["schema"]["maximum"] == 500
    description = schema["paths"]["/v2/parameters/children"]["get"]["description"]
    assert "422" in description
    assert "malformed policyengine_version" in description
    assert "503" in description


def test_parameter_children_openapi_declares_exactly_its_error_responses() -> None:
    results, _ids = resource_results()
    schema = (
        metadata_route_client(lambda: ResourceReader(results))
        .get("/v2/openapi.json")
        .json()
    )
    responses = schema["paths"]["/v2/parameters/children"]["get"]["responses"]
    parameter_responses = schema["paths"]["/v2/parameters"]["get"]["responses"]

    assert set(responses) == {"200", "304", "404", "405", "422", "500", "503"}
    assert "PolicyEngine.py version" in responses["422"]["description"]
    assert "parameter tree" in responses["503"]["description"]
    assert "parameter tree" not in parameter_responses["503"]["description"]


def test_parameter_tree_responses_are_cached_like_other_metadata() -> None:
    """A version's tree never changes, so it is cached as other metadata is."""
    results, _ids = resource_results()
    client = metadata_route_client(lambda: ResourceReader(results))
    path = "/v2/parameters/children?country_id=us&parent_path=gov.example"

    running = client.get(path, headers={"Origin": "https://app.policyengine.org"})
    named = client.get(f"{path}&policyengine_version=4.20.3")
    revalidated = client.get(
        f"{path}&policyengine_version=4.20.3",
        headers={"If-None-Match": named.headers["etag"]},
    )

    assert running.status_code == named.status_code == 200
    assert running.headers["cache-control"] == "public, max-age=300"
    assert named.headers["cache-control"] == "public, max-age=86400"
    assert running.headers["etag"]
    assert "origin" in vary_values(running)
    assert revalidated.status_code == 304
    assert revalidated.content == b""
    assert revalidated.headers["etag"] == named.headers["etag"]


def test_a_missing_parameter_tree_is_not_cached() -> None:
    results, _ids = resource_results()
    reader = ResourceReader(
        results,
        error=ParameterTreeUnavailableError("catalog version 4.20.3 has no tree"),
    )

    response = metadata_route_client(lambda: reader).get(
        "/v2/parameters/children",
        params={"country_id": "us", "policyengine_version": "4.20.3"},
    )

    assert response.status_code == 503
    assert "etag" not in response.headers
    assert "cache-control" not in response.headers
    assert "origin" not in vary_values(response)
