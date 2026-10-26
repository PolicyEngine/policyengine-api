"""Pin the rows that catalog publication COPYs into each staging table."""

from __future__ import annotations

import inspect
from dataclasses import replace

from psycopg.types.json import Jsonb

from policyengine_api.data.v2.catalog.publication_staging import (
    STAGE_CATALOG_VARIABLES,
    STAGING_TABLES,
    _catalog_rows,
)
from policyengine_api.data.v2.catalog.records import EnumValueRecord
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
            2,
            (
                "jsonb",
                [
                    {"key": "person", "plural": "people", "is_person": True},
                    {"key": "household", "plural": "households", "is_person": False},
                ],
            ),
            ("jsonb", ["employment_income"]),
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
            record.is_input_variable,
            record.hidden_input,
            record.module_name,
            record.adds_parameter_path,
            record.subtracts_parameter_path,
            None,
            record.unit,
            record.definition_period,
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
            record.economy,
            record.household,
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


def test_enum_values_are_staged_as_value_and_label_objects_in_order() -> None:
    country = normalized_catalog().country("us")
    variable = replace(
        country.variables[0],
        possible_values=["SINGLE", "JOINT"],
        enum_values=(
            EnumValueRecord(value="SINGLE", label="Single"),
            EnumValueRecord(value="JOINT", label=2),
        ),
    )
    country = replace(country, variables=(variable,))

    (row,) = (_plain(row) for row in _catalog_rows(country)[STAGE_CATALOG_VARIABLES])

    enum_values_column = [column.name for column in STAGE_CATALOG_VARIABLES.columns]
    assert row[enum_values_column.index("enum_values")] == (
        "jsonb",
        [{"value": "SINGLE", "label": "Single"}, {"value": "JOINT", "label": 2}],
    )
