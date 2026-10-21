"""Pin how the parameter-value listing route forwards its query to the reader."""

from __future__ import annotations

import pytest

from policyengine_api.services.v2.metadata.types import ParameterValueFilter

from .test_metadata_routes import ResourceReader, _client, _resource_results


def test_listing_forwards_every_query_parameter() -> None:
    results, ids = _resource_results()
    reader = ResourceReader(results)

    response = _client(lambda: reader).get(
        "/v2/parameter-values",
        params={
            "country_id": "uk",
            "policyengine_version": "4.19.0",
            "parameter_id": str(ids["parameter_id"]),
            "current": "true",
            "offset": 5,
            "limit": 7,
        },
    )

    assert response.status_code == 200
    assert reader.calls == [
        (
            "list_parameter_values",
            ("uk", "4.19.0"),
            {
                "value_filter": ParameterValueFilter(
                    parameter_id=ids["parameter_id"], current=True
                ),
                "offset": 5,
                "limit": 7,
            },
        )
    ]


def test_listing_defaults_to_every_value_on_the_first_page() -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results)

    response = _client(lambda: reader).get(
        "/v2/parameter-values", params={"country_id": "us"}
    )

    assert response.status_code == 200
    assert reader.calls == [
        (
            "list_parameter_values",
            ("us", None),
            {"value_filter": ParameterValueFilter(), "offset": 0, "limit": 100},
        )
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"country_id": "us", "current": "maybe"},
        {"country_id": "us", "parameter_id": "not-a-uuid"},
    ],
)
def test_invalid_listing_query_is_a_typed_422(params: dict[str, str]) -> None:
    results, _ids = _resource_results()
    reader = ResourceReader(results)

    response = _client(lambda: reader).get("/v2/parameter-values", params=params)

    assert response.status_code == 422
    assert response.json() == {"status": "error", "message": "Invalid API v2 request"}
    assert reader.calls == []
