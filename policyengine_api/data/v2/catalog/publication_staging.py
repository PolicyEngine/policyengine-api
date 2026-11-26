"""Temporary-table staging for v2 catalog publication.

Publication COPYs every country's catalog records into the staging tables
(``publication_staging_base``), which it creates in its own transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from psycopg import sql
from psycopg.types.json import Jsonb

from policyengine_api.data.v2.catalog.dynamic_parameter_records import (
    is_dynamic_record,
)
from policyengine_api.data.v2.catalog.publication_staging_base import (
    STAGING_METADATA,
    STAGING_MODELS,
    StagedDataset,
    StagedModel,
    StagedParameter,
    StagedParameterNode,
    StagedParameterValue,
    StagedRegion,
    StagedVariable,
)
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)
from policyengine_api.data.v2.catalog.records import (
    CountryCatalog,
    NormalizedCatalog,
    VariableRecord,
    iter_batches,
)
from policyengine_api.data.v2.models import CatalogEntity, CatalogEnumValue

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence
    from uuid import UUID

    from sqlalchemy.orm import Mapper
    from sqlmodel import Session, SQLModel

COPY_BATCH_SIZE = 10_000


def _optional_json(value: object) -> Jsonb | None:
    return None if value is None else Jsonb(value)


def _model_rows(country: CountryCatalog) -> Iterator[tuple[object, ...]]:
    """Yield the country's one model and model-version row."""
    yield (
        country.country_id,
        country.model.id,
        country.model.name,
        country.model.description,
        country.model_version.id,
        country.model_version.version,
        country.model_version.description,
        country.model_version.current_law_id,
        Jsonb(country.model_version.metadata_time_periods),
        country.model_version.catalog_format,
        Jsonb(
            [
                CatalogEntity(
                    key=entity.key,
                    plural=entity.plural,
                    is_person=entity.is_person,
                )
                for entity in country.model_version.entities
            ]
        ),
        Jsonb(list(country.model_version.basic_inputs)),
    )


def _enum_values_json(record: VariableRecord) -> Jsonb | None:
    """Return an enum variable's values as ordered value and label objects."""
    if record.enum_values is None:
        return None
    return Jsonb(
        [
            CatalogEnumValue(value=item.value, label=item.label)
            for item in record.enum_values
        ]
    )


def _variable_rows(country: CountryCatalog) -> Iterator[tuple[object, ...]]:
    """Yield one row per variable, in bounded batches."""
    for batch in iter_batches(country.variables, batch_size=COPY_BATCH_SIZE):
        for record in batch:
            yield (
                country.country_id,
                record.id,
                record.name,
                record.label,
                record.entity,
                record.description,
                record.data_type,
                _optional_json(record.possible_values),
                Jsonb(record.default_value),
                _optional_json(record.adds),
                _optional_json(record.subtracts),
                record.is_input_variable,
                record.hidden_input,
                record.module_name,
                record.adds_parameter_path,
                record.subtracts_parameter_path,
                _enum_values_json(record),
                record.unit,
                record.definition_period,
            )


def _parameter_node_rows(country: CountryCatalog) -> Iterator[tuple[object, ...]]:
    """Yield one row per parameter node, in bounded batches."""
    for batch in iter_batches(
        country.parameter_nodes,
        batch_size=COPY_BATCH_SIZE,
    ):
        for record in batch:
            yield (
                country.country_id,
                record.id,
                record.name,
                record.label,
                record.description,
            )


def _parameter_rows(country: CountryCatalog) -> Iterator[tuple[object, ...]]:
    """Yield one row per parameter, in bounded batches, marking model assumptions."""
    for batch in iter_batches(country.parameters, batch_size=COPY_BATCH_SIZE):
        for record in batch:
            yield (
                country.country_id,
                record.id,
                record.name,
                record.label,
                record.description,
                record.data_type,
                record.unit,
                record.economy,
                record.household,
                is_dynamic_record(country.country_id, record.name),
            )


def _parameter_value_rows(country: CountryCatalog) -> Iterator[tuple[object, ...]]:
    """Yield one row per parameter value, keyed by its parameter's name."""
    parameter_names = {parameter.id: parameter.name for parameter in country.parameters}
    for batch in country.parameter_value_batches(batch_size=COPY_BATCH_SIZE):
        for record in batch:
            yield (
                country.country_id,
                parameter_names[record.parameter_id],
                record.id,
                Jsonb(record.value_json),
                record.start_date,
                record.end_date,
            )


def _dataset_rows(country: CountryCatalog) -> Iterator[tuple[object, ...]]:
    """Yield one row per logical input dataset, in bounded batches."""
    for batch in iter_batches(country.datasets, batch_size=COPY_BATCH_SIZE):
        for record in batch:
            yield (
                country.country_id,
                record.id,
                record.name,
                record.description,
                record.year,
            )


def _region_rows(
    country: CountryCatalog,
    dataset_names: dict[UUID, str],
) -> Iterator[tuple[object, ...]]:
    """Yield one row per region, naming its default dataset."""
    for batch in iter_batches(country.regions, batch_size=COPY_BATCH_SIZE):
        for record in batch:
            yield (
                country.country_id,
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


def _catalog_rows(
    country: CountryCatalog,
) -> dict[type[SQLModel], Iterator[tuple[object, ...]]]:
    dataset_names = {dataset.id: dataset.name for dataset in country.datasets}
    return {
        StagedModel: _model_rows(country),
        StagedVariable: _variable_rows(country),
        StagedParameterNode: _parameter_node_rows(country),
        StagedParameter: _parameter_rows(country),
        StagedParameterValue: _parameter_value_rows(country),
        StagedDataset: _dataset_rows(country),
        StagedRegion: _region_rows(country, dataset_names),
    }


def table_name(model: type[SQLModel]) -> str:
    """Return the name of the table the mapped class ``model`` maps."""
    name = model.__tablename__
    if not isinstance(name, str):
        msg = f"{model.__name__} names no table"
        raise TypeError(msg)
    return name


def column_names(model: type[SQLModel]) -> list[str]:
    """Return the names of the mapped class's columns, in their declared order."""
    mapper: Mapper[Any] = sa.inspect(model)
    return [column.name for column in mapper.columns]


def copy_rows(
    session: Session,
    *,
    model: type[SQLModel],
    rows: Iterable[Sequence[object]],
) -> int:
    """Write one bounded source stream into ``model``'s table through Psycopg COPY.

    Each row gives the model's columns in their declared order. COPY runs on
    the psycopg connection beneath the Session's Connection, so it is part of
    the Session's transaction.
    """
    driver_connection = session.connection().connection.driver_connection
    if driver_connection is None:
        msg = "the publishing Session's connection is closed"
        raise CatalogPublicationError(msg)
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table_name(model)),
        sql.SQL(", ").join([sql.Identifier(name) for name in column_names(model)]),
    )
    count = 0
    with driver_connection.cursor() as cursor, cursor.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


def create_staging_tables(session: Session) -> None:
    """Create the temporary staging tables, which Postgres drops at commit.

    They are created on the Connection the Session holds, in its transaction.
    """
    STAGING_METADATA.create_all(session.connection(), checkfirst=False)


def stage_catalog(
    session: Session,
    catalog: NormalizedCatalog,
    *,
    checkpoint: Callable[[str, Session], None] | None = None,
) -> dict[str, int]:
    """COPY every country's records into the staging tables and return rows per table.

    Raise CatalogPublicationError if the copied counts differ from the
    catalog's own counts.
    """
    observed: dict[type[SQLModel], int] = dict.fromkeys(STAGING_MODELS, 0)
    for country in catalog.countries:
        for model, rows in _catalog_rows(country).items():
            observed[model] += copy_rows(session, model=model, rows=rows)
            if checkpoint is not None:
                checkpoint("during_copy", session)
    expected = catalog.entity_counts()
    expected_by_model = {
        StagedModel: expected["models"],
        StagedVariable: expected["variables"],
        StagedParameterNode: expected["parameter_nodes"],
        StagedParameter: expected["parameters"],
        StagedParameterValue: expected["parameter_values"],
        StagedDataset: expected["datasets"],
        StagedRegion: expected["regions"],
    }
    if observed != expected_by_model:
        msg = "COPY row counts differ from the catalog"
        raise CatalogPublicationError(msg)
    return {table_name(model): count for model, count in observed.items()}
