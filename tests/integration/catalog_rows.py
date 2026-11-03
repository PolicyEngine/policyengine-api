"""Read published catalog rows back from PostgreSQL and compare them with a catalog.

Every value is compared as strict JSON text, which tells 1, 1.0 and true
apart, so a value PostgreSQL stores in another form fails the comparison.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from policyengine_api.data.v2.catalog.records import NormalizedCatalog

# The columns each catalog table stores, named as on the catalog's records:
# each table's key column first. Each country catalog names its records after
# the table that stores them.
CATALOG_COLUMNS = {
    "variables": (
        "name",
        "label",
        "entity",
        "description",
        "data_type",
        "possible_values",
        "default_value",
        "adds",
        "subtracts",
    ),
    "parameter_nodes": ("name", "label", "description"),
    "parameters": ("name", "label", "description", "data_type", "unit"),
    "regions": (
        "code",
        "label",
        "region_type",
        "requires_filter",
        "filter_field",
        "filter_value",
        "filter_strategy",
        "parent_code",
        "state_code",
        "state_name",
        "default_dataset_id",
    ),
}


def strict_json(value: object) -> str:
    """Return ``value`` as JSON text, which tells 1, 1.0 and true apart."""
    return json.dumps(value, sort_keys=True, default=str)


def stored_catalog_rows(engine: Engine, table_name: str) -> dict[tuple, str]:
    """Return each row of a catalog table, keyed by model and name or code."""
    key_column, *columns = CATALOG_COLUMNS[table_name]
    selected = ", ".join(f"catalog_row.{column}" for column in (key_column, *columns))
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                f"""
                SELECT model.name, {selected}
                FROM {table_name} AS catalog_row
                JOIN tax_benefit_model_versions AS version
                  ON version.id = catalog_row.tax_benefit_model_version_id
                JOIN tax_benefit_models AS model ON model.id = version.model_id
                """
            )
        ).all()
    return {(row[0], row[1]): strict_json(row[2:]) for row in rows}


def catalog_rows(catalog: NormalizedCatalog, table_name: str) -> dict[tuple, str]:
    """Return what ``stored_catalog_rows`` should read for ``catalog``."""
    key_column, *columns = CATALOG_COLUMNS[table_name]
    return {
        (country.model.name, getattr(record, key_column)): strict_json(
            [getattr(record, column) for column in columns]
        )
        for country in catalog.countries
        for record in getattr(country, table_name)
    }


def stored_parameter_values(engine: Engine) -> dict[tuple, tuple]:
    """Return each parameter value's JSON and end date, by model, name and start."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT model.name, parameter.name, parameter_value.start_date,
                       parameter_value.value_json, parameter_value.end_date
                FROM parameter_values AS parameter_value
                JOIN parameters AS parameter
                  ON parameter.id = parameter_value.parameter_id
                JOIN tax_benefit_model_versions AS version
                  ON version.id = parameter.tax_benefit_model_version_id
                JOIN tax_benefit_models AS model ON model.id = version.model_id
                """
            )
        ).all()
    return {
        (model_name, parameter_name, start_date): (strict_json(value_json), end_date)
        for model_name, parameter_name, start_date, value_json, end_date in rows
    }


def catalog_parameter_values(catalog: NormalizedCatalog) -> dict[tuple, tuple]:
    """Return what ``stored_parameter_values`` should read for ``catalog``."""
    return {
        (country.model.name, parameter.name, value.start_date): (
            strict_json(value.value_json),
            value.end_date,
        )
        for country in catalog.countries
        for parameter in country.parameters
        for value in parameter.values
    }


def assert_catalog_stored_unchanged(engine: Engine, catalog: NormalizedCatalog) -> None:
    """Assert that the database holds exactly ``catalog``'s values and records."""
    assert stored_parameter_values(engine) == catalog_parameter_values(catalog)
    for table_name in CATALOG_COLUMNS:
        assert stored_catalog_rows(engine, table_name) == catalog_rows(
            catalog, table_name
        ), table_name
