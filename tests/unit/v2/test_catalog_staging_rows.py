"""Pin the rows that catalog publication COPYs into each staging table."""

from __future__ import annotations

import inspect

from psycopg.types.json import Jsonb

from policyengine_api.data.v2.catalog.publication_staging import (
    STAGING_TABLES,
    _catalog_rows,
)
from tests.fixtures.v2_catalog import normalized_catalog


def _plain(row: tuple[object, ...]) -> tuple[object, ...]:
    return tuple(
        ("jsonb", value.obj) if isinstance(value, Jsonb) else value for value in row
    )


def test_catalog_rows_stream_every_staging_table_lazily_in_table_order() -> None:
    country = normalized_catalog().country("us")

    rows_by_table = _catalog_rows(country)

    assert list(rows_by_table) == list(STAGING_TABLES)
    assert all(inspect.isgenerator(rows) for rows in rows_by_table.values())


def test_catalog_rows_project_every_record_field_in_column_order() -> None:
    country = normalized_catalog().country("us")
    dataset_names = {dataset.id: dataset.name for dataset in country.datasets}
    parameter_names = {parameter.id: parameter.name for parameter in country.parameters}

    rows = {
        table.name: [_plain(row) for row in table_rows]
        for table, table_rows in _catalog_rows(country).items()
    }

    assert rows["stage_catalog_models"] == [
        (
            "us",
            country.model.id,
            country.model.name,
            country.model.description,
            country.model_version.id,
            country.model_version.version,
            country.model_version.description,
            country.model_version.current_law_id,
            ("jsonb", country.model_version.metadata_time_periods),
        )
    ]
    assert rows["stage_catalog_variables"] == [
        (
            "us",
            record.id,
            record.name,
            record.label,
            record.entity,
            record.description,
            record.data_type,
            None
            if record.possible_values is None
            else ("jsonb", record.possible_values),
            ("jsonb", record.default_value),
            None if record.adds is None else ("jsonb", record.adds),
            None if record.subtracts is None else ("jsonb", record.subtracts),
        )
        for record in country.variables
    ]
    assert rows["stage_catalog_parameter_nodes"] == [
        ("us", record.id, record.name, record.label, record.description)
        for record in country.parameter_nodes
    ]
    assert rows["stage_catalog_parameters"] == [
        (
            "us",
            record.id,
            record.name,
            record.label,
            record.description,
            record.data_type,
            record.unit,
        )
        for record in country.parameters
    ]
    assert rows["stage_catalog_parameter_values"] == [
        (
            "us",
            parameter_names[record.parameter_id],
            record.id,
            ("jsonb", record.value_json),
            record.start_date,
            record.end_date,
        )
        for parameter in country.parameters
        for record in parameter.values
    ]
    assert rows["stage_catalog_datasets"] == [
        ("us", record.id, record.name, record.description, record.year)
        for record in country.datasets
    ]
    assert rows["stage_catalog_regions"] == [
        (
            "us",
            record.id,
            record.code,
            record.label,
            record.region_type,
            record.requires_filter,
            record.filter_field,
            record.filter_value,
            record.filter_strategy,
            record.parent_code,
            record.state_code,
            record.state_name,
            dataset_names[record.default_dataset_id],
        )
        for record in country.regions
    ]
    assert len(rows["stage_catalog_parameter_values"]) == 2
    assert len(rows["stage_catalog_regions"]) == 3
