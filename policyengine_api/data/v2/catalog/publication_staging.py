"""Temporary-table staging for v2 catalog publication."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence

from psycopg import sql
from psycopg.types.json import Jsonb
import sqlalchemy as sa
from sqlalchemy import Connection, MetaData, Table
from sqlalchemy.dialects.postgresql import JSONB

from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)
from policyengine_api.data.v2.catalog.records import (
    CountryCatalog,
    NormalizedCatalog,
    iter_batches,
)


COPY_BATCH_SIZE = 10_000

STAGING_METADATA = MetaData()

STAGE_CATALOG_MODELS = Table(
    "stage_catalog_models",
    STAGING_METADATA,
    sa.Column("country_id", sa.Text, primary_key=True),
    sa.Column("id", sa.Uuid, nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("description", sa.Text),
    sa.Column("version_id", sa.Uuid, nullable=False),
    sa.Column("version", sa.Text, nullable=False),
    sa.Column("version_description", sa.Text),
    sa.Column("current_law_id", sa.Integer, nullable=False),
    sa.Column("metadata_time_periods", JSONB, nullable=False),
    prefixes=["TEMPORARY"],
    postgresql_on_commit="DROP",
)

STAGE_CATALOG_VARIABLES = Table(
    "stage_catalog_variables",
    STAGING_METADATA,
    sa.Column("country_id", sa.Text, primary_key=True),
    sa.Column("id", sa.Uuid, nullable=False),
    sa.Column("name", sa.Text, primary_key=True),
    sa.Column("label", sa.Text),
    sa.Column("entity", sa.Text, nullable=False),
    sa.Column("description", sa.Text),
    sa.Column("data_type", sa.Text),
    sa.Column("possible_values", JSONB),
    sa.Column("default_value", JSONB, nullable=False),
    sa.Column("adds", JSONB),
    sa.Column("subtracts", JSONB),
    prefixes=["TEMPORARY"],
    postgresql_on_commit="DROP",
)

STAGE_CATALOG_PARAMETER_NODES = Table(
    "stage_catalog_parameter_nodes",
    STAGING_METADATA,
    sa.Column("country_id", sa.Text, primary_key=True),
    sa.Column("id", sa.Uuid, nullable=False),
    sa.Column("name", sa.Text, primary_key=True),
    sa.Column("label", sa.Text),
    sa.Column("description", sa.Text),
    prefixes=["TEMPORARY"],
    postgresql_on_commit="DROP",
)

STAGE_CATALOG_PARAMETERS = Table(
    "stage_catalog_parameters",
    STAGING_METADATA,
    sa.Column("country_id", sa.Text, primary_key=True),
    sa.Column("id", sa.Uuid, nullable=False),
    sa.Column("name", sa.Text, primary_key=True),
    sa.Column("label", sa.Text),
    sa.Column("description", sa.Text),
    sa.Column("data_type", sa.Text),
    sa.Column("unit", sa.Text),
    prefixes=["TEMPORARY"],
    postgresql_on_commit="DROP",
)

STAGE_CATALOG_PARAMETER_VALUES = Table(
    "stage_catalog_parameter_values",
    STAGING_METADATA,
    sa.Column("country_id", sa.Text, primary_key=True),
    sa.Column("parameter_name", sa.Text, primary_key=True),
    sa.Column("id", sa.Uuid, nullable=False),
    sa.Column("value_json", JSONB, nullable=False),
    sa.Column(
        "start_date",
        sa.DateTime(timezone=True),
        primary_key=True,
    ),
    sa.Column("end_date", sa.DateTime(timezone=True)),
    prefixes=["TEMPORARY"],
    postgresql_on_commit="DROP",
)

STAGE_CATALOG_DATASETS = Table(
    "stage_catalog_datasets",
    STAGING_METADATA,
    sa.Column("country_id", sa.Text, primary_key=True),
    sa.Column("id", sa.Uuid, nullable=False),
    sa.Column("name", sa.Text, primary_key=True),
    sa.Column("description", sa.Text),
    sa.Column("year", sa.Integer, nullable=False),
    prefixes=["TEMPORARY"],
    postgresql_on_commit="DROP",
)

STAGE_CATALOG_REGIONS = Table(
    "stage_catalog_regions",
    STAGING_METADATA,
    sa.Column("country_id", sa.Text, primary_key=True),
    sa.Column("id", sa.Uuid, nullable=False),
    sa.Column("code", sa.Text, primary_key=True),
    sa.Column("label", sa.Text, nullable=False),
    sa.Column("region_type", sa.Text, nullable=False),
    sa.Column("requires_filter", sa.Boolean, nullable=False),
    sa.Column("filter_field", sa.Text),
    sa.Column("filter_value", sa.Text),
    sa.Column("filter_strategy", sa.Text),
    sa.Column("parent_code", sa.Text),
    sa.Column("state_code", sa.Text),
    sa.Column("state_name", sa.Text),
    sa.Column("default_dataset_name", sa.Text, nullable=False),
    prefixes=["TEMPORARY"],
    postgresql_on_commit="DROP",
)

STAGING_TABLES = (
    STAGE_CATALOG_MODELS,
    STAGE_CATALOG_VARIABLES,
    STAGE_CATALOG_PARAMETER_NODES,
    STAGE_CATALOG_PARAMETERS,
    STAGE_CATALOG_PARAMETER_VALUES,
    STAGE_CATALOG_DATASETS,
    STAGE_CATALOG_REGIONS,
)


def _optional_json(value: object) -> Jsonb | None:
    return None if value is None else Jsonb(value)


def _catalog_rows(
    country: CountryCatalog,
) -> dict[Table, Iterator[tuple[object, ...]]]:
    dataset_names = {dataset.id: dataset.name for dataset in country.datasets}

    def model_rows() -> Iterator[tuple[object, ...]]:
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
        )

    def variable_rows() -> Iterator[tuple[object, ...]]:
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
                )

    def parameter_node_rows() -> Iterator[tuple[object, ...]]:
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

    def parameter_rows() -> Iterator[tuple[object, ...]]:
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
                )

    def parameter_value_rows() -> Iterator[tuple[object, ...]]:
        parameter_names = {
            parameter.id: parameter.name for parameter in country.parameters
        }
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

    def dataset_rows() -> Iterator[tuple[object, ...]]:
        for batch in iter_batches(country.datasets, batch_size=COPY_BATCH_SIZE):
            for record in batch:
                yield (
                    country.country_id,
                    record.id,
                    record.name,
                    record.description,
                    record.year,
                )

    def region_rows() -> Iterator[tuple[object, ...]]:
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

    return {
        STAGE_CATALOG_MODELS: model_rows(),
        STAGE_CATALOG_VARIABLES: variable_rows(),
        STAGE_CATALOG_PARAMETER_NODES: parameter_node_rows(),
        STAGE_CATALOG_PARAMETERS: parameter_rows(),
        STAGE_CATALOG_PARAMETER_VALUES: parameter_value_rows(),
        STAGE_CATALOG_DATASETS: dataset_rows(),
        STAGE_CATALOG_REGIONS: region_rows(),
    }


def copy_rows(
    connection: Connection,
    *,
    table: Table,
    rows: Iterable[Sequence[object]],
) -> int:
    """Write one bounded source stream through Psycopg COPY."""

    raw_connection = connection.connection.driver_connection
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table.name),
        sql.SQL(", ").join(sql.Identifier(column.name) for column in table.columns),
    )
    count = 0
    with raw_connection.cursor() as cursor:
        with cursor.copy(statement) as copy:
            for row in rows:
                copy.write_row(row)
                count += 1
    return count


def create_staging_tables(connection: Connection) -> None:
    STAGING_METADATA.create_all(connection, checkfirst=False)


def stage_catalog(
    connection: Connection,
    catalog: NormalizedCatalog,
    *,
    checkpoint: Callable[[str, Connection], None] | None = None,
) -> dict[str, int]:
    observed = {table.name: 0 for table in STAGING_TABLES}
    for country in catalog.countries:
        for table, rows in _catalog_rows(country).items():
            observed[table.name] += copy_rows(
                connection,
                table=table,
                rows=rows,
            )
            if checkpoint is not None:
                checkpoint("during_copy", connection)
    expected = catalog.entity_counts()
    expected_by_table = {
        STAGE_CATALOG_MODELS.name: expected["models"],
        STAGE_CATALOG_VARIABLES.name: expected["variables"],
        STAGE_CATALOG_PARAMETER_NODES.name: expected["parameter_nodes"],
        STAGE_CATALOG_PARAMETERS.name: expected["parameters"],
        STAGE_CATALOG_PARAMETER_VALUES.name: expected["parameter_values"],
        STAGE_CATALOG_DATASETS.name: expected["datasets"],
        STAGE_CATALOG_REGIONS.name: expected["regions"],
    }
    if observed != expected_by_table:
        raise CatalogPublicationError("COPY row counts differ from the catalog")
    return observed
