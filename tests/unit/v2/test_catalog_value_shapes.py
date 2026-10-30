"""The value-shape catalog holds an example of each shape extraction accepts.

Every pull request publishes it to PostgreSQL
(tests/integration/test_v2_catalog_publication.py), while the complete
installed catalog runs only when a change can affect it. These tests fail when
extraction accepts a shape the value-shape catalog leaves out, or stores one
differently from what the catalog says it stores.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from policyengine_api.data.v2.catalog.extraction_values import JSON_VALUE_NORMALIZERS
from tests.fixtures.v2_catalog_value_shapes import (
    BRACKET_PARAMETER_NODES,
    PARAMETER_CASES,
    REGION_FILTER_VALUES,
    value_shape_catalog,
)


def _source_values() -> list[object]:
    return [value.value for case in PARAMETER_CASES for value in case.values]


def _strict_json(value: object) -> str:
    """Return ``value`` as JSON text, which tells 1, 1.0 and true apart."""
    return json.dumps(value, sort_keys=True)


def test_holds_a_value_for_each_json_normalizer() -> None:
    source_values = _source_values()

    for value_types, _normalize in JSON_VALUE_NORMALIZERS:
        assert any(isinstance(value, value_types) for value in source_values), (
            value_types
        )


def test_holds_each_plain_json_value_and_scalar_wrapper() -> None:
    source_values = _source_values()
    plain_types = (type(None), str, bool, int, float, list, tuple, dict)

    assert any(value is None for value in source_values)
    assert any(value is True for value in source_values)
    assert any(value is False for value in source_values)
    assert any(type(value) is int for value in source_values)
    assert any(type(value) is str for value in source_values)
    assert any(type(value) is float and value.is_integer() for value in source_values)
    assert any(value == float("inf") for value in source_values)
    assert any(value == float("-inf") for value in source_values)
    # NumPy scalars that are no Python number, read through their item().
    assert any(
        not isinstance(value, plain_types) and callable(getattr(value, "item", None))
        for value in source_values
    )


def test_holds_each_date_form_and_range() -> None:
    values = [value for case in PARAMETER_CASES for value in case.values]
    us = value_shape_catalog().country("us")
    stored_values = [value for parameter in us.parameters for value in parameter.values]

    assert any(type(value.start) is date for value in values)
    assert any(
        isinstance(value.start, datetime) and value.start.tzinfo is None
        for value in values
    )
    # Core writes its earliest instant as 0000-01-01, which .py reads as year 1.
    assert any(
        value.start_date == datetime(1, 1, 1, tzinfo=UTC) for value in stored_values
    )
    # A value in force for a single day, then one in force from the next day.
    assert any(value.start_date == value.end_date for value in stored_values)
    assert all(parameter.values[-1].end_date is None for parameter in us.parameters)


def test_extraction_stores_what_each_case_says() -> None:
    us = value_shape_catalog().country("us")
    parameters = {parameter.name: parameter for parameter in us.parameters}

    for case in PARAMETER_CASES:
        assert [
            _strict_json(value.value_json) for value in parameters[case.name].values
        ] == [_strict_json(value.stored_value) for value in case.values], case.name


def test_holds_bracket_parameters_and_their_nodes() -> None:
    us = value_shape_catalog().country("us")
    node_names = {node.name for node in us.parameter_nodes}
    bracket_parameters = [
        parameter.name for parameter in us.parameters if "[" in parameter.name
    ]

    assert set(BRACKET_PARAMETER_NODES) <= node_names
    for node_name in BRACKET_PARAMETER_NODES:
        assert f"{node_name}.rate" in bracket_parameters
        assert f"{node_name}.threshold" in bracket_parameters


def test_holds_each_region_filter_form() -> None:
    catalog = value_shape_catalog()
    filter_values = {
        (country.country_id, region.code): region.filter_value
        for country in catalog.countries
        for region in country.regions
    }
    filtered = [
        region
        for country in catalog.countries
        for region in country.regions
        if region.requires_filter
    ]
    unfiltered_subnational = [
        region
        for country in catalog.countries
        for region in country.regions
        if not region.requires_filter and region.region_type != "national"
    ]

    assert {key: filter_values[key] for key in REGION_FILTER_VALUES} == (
        REGION_FILTER_VALUES
    )
    # A scalar text filter, a number written as text and a JSON membership list.
    stored_forms = set(REGION_FILTER_VALUES.values())
    assert any(value.isdigit() for value in stored_forms)
    assert any(value.startswith("[") for value in stored_forms)
    assert any(value.isalpha() for value in stored_forms)
    assert all(region.filter_strategy == "row_filter" for region in filtered)
    assert unfiltered_subnational
