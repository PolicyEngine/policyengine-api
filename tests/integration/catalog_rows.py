"""Read published catalog rows back from PostgreSQL and compare them with a catalog.

Every value is compared as strict JSON text, which tells 1, 1.0 and true
apart, so a value PostgreSQL stores in another form fails the comparison.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlmodel import col

from policyengine_api.data.v2.models import (
    Parameter,
    ParameterNode,
    ParameterValue,
    Region,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    Variable,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from policyengine_api.data.v2.catalog.records import NormalizedCatalog

# The mapped class of each catalog table, by the table's name.
CATALOG_MODELS: dict[str, Any] = {
    "variables": Variable,
    "parameter_nodes": ParameterNode,
    "parameters": Parameter,
    "regions": Region,
}
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


def stored_catalog_rows(
    sessions: sessionmaker[Session], table_name: str
) -> dict[tuple, str]:
    """Return each row of a catalog table, keyed by model and name or code."""
    model = CATALOG_MODELS[table_name]
    selected = [getattr(model, column) for column in CATALOG_COLUMNS[table_name]]
    with sessions.begin() as session:
        rows = session.execute(
            select(col(TaxBenefitModel.name), *selected)
            .join(
                TaxBenefitModelVersion,
                col(TaxBenefitModelVersion.id) == model.tax_benefit_model_version_id,
            )
            .join(
                TaxBenefitModel,
                col(TaxBenefitModel.id) == TaxBenefitModelVersion.model_id,
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


def stored_parameter_values(sessions: sessionmaker[Session]) -> dict[tuple, tuple]:
    """Return each parameter value's JSON and end date, by model, name and start."""
    with sessions.begin() as session:
        rows = session.execute(
            select(
                col(TaxBenefitModel.name),
                col(Parameter.name),
                col(ParameterValue.start_date),
                col(ParameterValue.value_json),
                col(ParameterValue.end_date),
            )
            .join(Parameter, col(Parameter.id) == ParameterValue.parameter_id)
            .join(
                TaxBenefitModelVersion,
                col(TaxBenefitModelVersion.id)
                == Parameter.tax_benefit_model_version_id,
            )
            .join(
                TaxBenefitModel,
                col(TaxBenefitModel.id) == TaxBenefitModelVersion.model_id,
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


def assert_catalog_stored_unchanged(
    sessions: sessionmaker[Session], catalog: NormalizedCatalog
) -> None:
    """Assert that the database holds exactly ``catalog``'s values and records."""
    assert stored_parameter_values(sessions) == catalog_parameter_values(catalog)
    for table_name in CATALOG_COLUMNS:
        assert stored_catalog_rows(sessions, table_name) == catalog_rows(
            catalog, table_name
        ), table_name
