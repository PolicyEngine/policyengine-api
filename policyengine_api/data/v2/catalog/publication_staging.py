"""Temporary-table staging for v2 catalog publication."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence

from psycopg.types.json import Jsonb
from sqlalchemy import Connection, text

from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)
from policyengine_api.data.v2.catalog.records import (
    CountryCatalog,
    NormalizedCatalog,
    iter_batches,
)


COPY_BATCH_SIZE = 10_000

TEMP_TABLE_STATEMENTS = (
    """
    CREATE TEMP TABLE stage_catalog_models (
        country_id text PRIMARY KEY,
        id uuid NOT NULL,
        name text NOT NULL,
        description text,
        version_id uuid NOT NULL,
        version text NOT NULL,
        version_description text,
        current_law_id integer NOT NULL,
        metadata_time_periods jsonb NOT NULL
    ) ON COMMIT DROP
    """,
    """
    CREATE TEMP TABLE stage_catalog_variables (
        country_id text NOT NULL,
        id uuid NOT NULL,
        name text NOT NULL,
        label text,
        entity text NOT NULL,
        description text,
        data_type text,
        possible_values jsonb,
        default_value jsonb,
        adds jsonb,
        subtracts jsonb,
        PRIMARY KEY (country_id, name)
    ) ON COMMIT DROP
    """,
    """
    CREATE TEMP TABLE stage_catalog_parameter_nodes (
        country_id text NOT NULL,
        id uuid NOT NULL,
        name text NOT NULL,
        label text,
        description text,
        PRIMARY KEY (country_id, name)
    ) ON COMMIT DROP
    """,
    """
    CREATE TEMP TABLE stage_catalog_parameters (
        country_id text NOT NULL,
        id uuid NOT NULL,
        name text NOT NULL,
        label text,
        description text,
        data_type text,
        unit text,
        PRIMARY KEY (country_id, name)
    ) ON COMMIT DROP
    """,
    """
    CREATE TEMP TABLE stage_catalog_parameter_values (
        country_id text NOT NULL,
        parameter_name text NOT NULL,
        id uuid NOT NULL,
        value_json jsonb NOT NULL,
        start_date timestamptz NOT NULL,
        end_date timestamptz,
        PRIMARY KEY (country_id, parameter_name, start_date)
    ) ON COMMIT DROP
    """,
    """
    CREATE TEMP TABLE stage_catalog_datasets (
        country_id text NOT NULL,
        id uuid NOT NULL,
        name text NOT NULL,
        description text,
        year integer NOT NULL,
        PRIMARY KEY (country_id, name)
    ) ON COMMIT DROP
    """,
    """
    CREATE TEMP TABLE stage_catalog_regions (
        country_id text NOT NULL,
        id uuid NOT NULL,
        code text NOT NULL,
        label text NOT NULL,
        region_type text NOT NULL,
        requires_filter boolean NOT NULL,
        filter_field text,
        filter_value text,
        filter_strategy text,
        parent_code text,
        state_code text,
        state_name text,
        default_dataset_name text NOT NULL,
        PRIMARY KEY (country_id, code)
    ) ON COMMIT DROP
    """,
)

COPY_COLUMNS = {
    "stage_catalog_models": (
        "country_id",
        "id",
        "name",
        "description",
        "version_id",
        "version",
        "version_description",
        "current_law_id",
        "metadata_time_periods",
    ),
    "stage_catalog_variables": (
        "country_id",
        "id",
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
    "stage_catalog_parameter_nodes": (
        "country_id",
        "id",
        "name",
        "label",
        "description",
    ),
    "stage_catalog_parameters": (
        "country_id",
        "id",
        "name",
        "label",
        "description",
        "data_type",
        "unit",
    ),
    "stage_catalog_parameter_values": (
        "country_id",
        "parameter_name",
        "id",
        "value_json",
        "start_date",
        "end_date",
    ),
    "stage_catalog_datasets": (
        "country_id",
        "id",
        "name",
        "description",
        "year",
    ),
    "stage_catalog_regions": (
        "country_id",
        "id",
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
        "default_dataset_name",
    ),
}


def _optional_json(value: object) -> Jsonb | None:
    return None if value is None else Jsonb(value)


def _catalog_rows(
    country: CountryCatalog,
) -> dict[str, Iterator[tuple[object, ...]]]:
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
        "stage_catalog_models": model_rows(),
        "stage_catalog_variables": variable_rows(),
        "stage_catalog_parameter_nodes": parameter_node_rows(),
        "stage_catalog_parameters": parameter_rows(),
        "stage_catalog_parameter_values": parameter_value_rows(),
        "stage_catalog_datasets": dataset_rows(),
        "stage_catalog_regions": region_rows(),
    }


def copy_rows(
    connection: Connection,
    *,
    table_name: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[object]],
) -> int:
    """Write one bounded source stream through Psycopg COPY."""

    raw_connection = connection.connection.driver_connection
    statement = f"COPY {table_name} ({', '.join(columns)}) FROM STDIN"
    count = 0
    with raw_connection.cursor() as cursor:
        with cursor.copy(statement) as copy:
            for row in rows:
                copy.write_row(row)
                count += 1
    return count


def create_staging_tables(connection: Connection) -> None:
    for statement in TEMP_TABLE_STATEMENTS:
        connection.execute(text(statement))


def stage_catalog(
    connection: Connection,
    catalog: NormalizedCatalog,
    *,
    checkpoint: Callable[[str, Connection], None] | None = None,
) -> dict[str, int]:
    observed = {table_name: 0 for table_name in COPY_COLUMNS}
    for country in catalog.countries:
        for table_name, rows in _catalog_rows(country).items():
            observed[table_name] += copy_rows(
                connection,
                table_name=table_name,
                columns=COPY_COLUMNS[table_name],
                rows=rows,
            )
            if checkpoint is not None:
                checkpoint("during_copy", connection)
    expected = catalog.entity_counts()
    expected_by_table = {
        "stage_catalog_models": expected["models"],
        "stage_catalog_variables": expected["variables"],
        "stage_catalog_parameter_nodes": expected["parameter_nodes"],
        "stage_catalog_parameters": expected["parameters"],
        "stage_catalog_parameter_values": expected["parameter_values"],
        "stage_catalog_datasets": expected["datasets"],
        "stage_catalog_regions": expected["regions"],
    }
    if observed != expected_by_table:
        raise CatalogPublicationError("COPY row counts differ from the catalog")
    return observed
