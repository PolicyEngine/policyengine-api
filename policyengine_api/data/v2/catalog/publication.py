"""Atomic PostgreSQL publication for a validated PolicyEngine.py catalog."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
import logging
import time

from psycopg.types.json import Jsonb
from sqlalchemy import Connection, Engine, text

from policyengine_api.data.v2.catalog.records import (
    CountryCatalog,
    NormalizedCatalog,
    iter_batches,
)


EXPECTED_ALEMBIC_REVISION = "68b4a5ae5dc5"
PUBLICATION_ADVISORY_LOCK_KEY = 8_629_020_026_090_001
COPY_BATCH_SIZE = 10_000

LOGGER = logging.getLogger(__name__)


class CatalogPublicationError(RuntimeError):
    """Raised when publication cannot prove an atomic, complete result."""


@dataclass(frozen=True, slots=True)
class PublicationEvidence:
    """Non-secret facts emitted after a successful publication."""

    policyengine_version: str
    dependency_versions: tuple[tuple[str, str], ...]
    entity_counts: dict[str, int]
    fallback_summaries: tuple[tuple[str, str, int], ...]
    elapsed_seconds: float

    def as_dict(self) -> dict[str, object]:
        return {
            "outcome": "ok",
            "policyengine_version": self.policyengine_version,
            "dependency_versions": dict(self.dependency_versions),
            "entity_counts": self.entity_counts,
            "fallback_summaries": [
                {
                    "country_id": country_id,
                    "region_type": region_type,
                    "count": count,
                }
                for country_id, region_type, count in self.fallback_summaries
            ],
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }


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


def _copy_rows(
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


def _verify_expected_revision(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        raise CatalogPublicationError("catalog publication requires PostgreSQL")
    version_table = connection.execute(
        text("SELECT to_regclass('public.alembic_version')")
    ).scalar_one()
    if version_table is None:
        raise CatalogPublicationError("the v2 Alembic revision table is absent")
    revisions = set(
        connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
    )
    if revisions != {EXPECTED_ALEMBIC_REVISION}:
        raise CatalogPublicationError(
            "the v2 database is not at the expected Alembic revision"
        )


def _acquire_publication_lock(connection: Connection) -> None:
    connection.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": PUBLICATION_ADVISORY_LOCK_KEY},
    ).scalar_one()


def _create_staging_tables(connection: Connection) -> None:
    for statement in TEMP_TABLE_STATEMENTS:
        connection.execute(text(statement))


def _stage_catalog(
    connection: Connection,
    catalog: NormalizedCatalog,
    *,
    checkpoint: Callable[[str, Connection], None] | None = None,
) -> dict[str, int]:
    observed = {table_name: 0 for table_name in COPY_COLUMNS}
    for country in catalog.countries:
        for table_name, rows in _catalog_rows(country).items():
            observed[table_name] += _copy_rows(
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


def _protected_row_counts(connection: Connection) -> tuple[int, int, int, int]:
    return tuple(
        connection.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one()
        for table_name in (
            "dataset_versions",
            "simulations",
            "reports",
            "report_runs",
        )
    )


def _version_exists(connection: Connection, country_id: str) -> bool:
    return bool(
        connection.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM stage_catalog_models AS source
                    JOIN tax_benefit_models AS model
                      ON model.name = source.name
                    JOIN tax_benefit_model_versions AS model_version
                      ON model_version.model_id = model.id
                     AND model_version.version = source.version
                    WHERE source.country_id = :country_id
                )
                """
            ),
            {"country_id": country_id},
        ).scalar_one()
    )


MODEL_DIFFERENCE_SQL = """
SELECT EXISTS (
    SELECT 1
    FROM stage_catalog_models AS source
    JOIN tax_benefit_models AS model ON model.name = source.name
    JOIN tax_benefit_model_versions AS model_version
      ON model_version.model_id = model.id
     AND model_version.version = source.version
    WHERE source.country_id = :country_id
      AND (
          model_version.description IS DISTINCT FROM source.version_description
          OR model_version.current_law_id IS DISTINCT FROM source.current_law_id
          OR model_version.metadata_time_periods::jsonb
             IS DISTINCT FROM source.metadata_time_periods
      )
)
"""


VERSIONED_DIFFERENCE_SQL = (
    """
    WITH staged AS (
        SELECT name, label, entity, description, data_type, possible_values,
               default_value, adds, subtracts
        FROM stage_catalog_variables
        WHERE country_id = :country_id
    ), actual AS (
        SELECT variable.name, variable.label, variable.entity,
               variable.description, variable.data_type,
               variable.possible_values::jsonb,
               variable.default_value::jsonb,
               variable.adds::jsonb, variable.subtracts::jsonb
        FROM variables AS variable
        JOIN tax_benefit_model_versions AS model_version
          ON model_version.id = variable.tax_benefit_model_version_id
        JOIN tax_benefit_models AS model ON model.id = model_version.model_id
        JOIN stage_catalog_models AS source
          ON source.name = model.name AND source.version = model_version.version
        WHERE source.country_id = :country_id
    ), differences AS (
        (SELECT * FROM staged EXCEPT SELECT * FROM actual)
        UNION ALL
        (SELECT * FROM actual EXCEPT SELECT * FROM staged)
    ) SELECT EXISTS (SELECT 1 FROM differences)
    """,
    """
    WITH staged AS (
        SELECT name, label, description
        FROM stage_catalog_parameter_nodes
        WHERE country_id = :country_id
    ), actual AS (
        SELECT node.name, node.label, node.description
        FROM parameter_nodes AS node
        JOIN tax_benefit_model_versions AS model_version
          ON model_version.id = node.tax_benefit_model_version_id
        JOIN tax_benefit_models AS model ON model.id = model_version.model_id
        JOIN stage_catalog_models AS source
          ON source.name = model.name AND source.version = model_version.version
        WHERE source.country_id = :country_id
    ), differences AS (
        (SELECT * FROM staged EXCEPT SELECT * FROM actual)
        UNION ALL
        (SELECT * FROM actual EXCEPT SELECT * FROM staged)
    ) SELECT EXISTS (SELECT 1 FROM differences)
    """,
    """
    WITH staged AS (
        SELECT name, label, description, data_type, unit
        FROM stage_catalog_parameters
        WHERE country_id = :country_id
    ), actual AS (
        SELECT parameter.name, parameter.label, parameter.description,
               parameter.data_type, parameter.unit
        FROM parameters AS parameter
        JOIN tax_benefit_model_versions AS model_version
          ON model_version.id = parameter.tax_benefit_model_version_id
        JOIN tax_benefit_models AS model ON model.id = model_version.model_id
        JOIN stage_catalog_models AS source
          ON source.name = model.name AND source.version = model_version.version
        WHERE source.country_id = :country_id
    ), differences AS (
        (SELECT * FROM staged EXCEPT SELECT * FROM actual)
        UNION ALL
        (SELECT * FROM actual EXCEPT SELECT * FROM staged)
    ) SELECT EXISTS (SELECT 1 FROM differences)
    """,
    """
    WITH staged AS (
        SELECT parameter_name, value_json, start_date, end_date
        FROM stage_catalog_parameter_values
        WHERE country_id = :country_id
    ), actual AS (
        SELECT parameter.name, parameter_value.value_json::jsonb,
               parameter_value.start_date, parameter_value.end_date
        FROM parameter_values AS parameter_value
        JOIN parameters AS parameter ON parameter.id = parameter_value.parameter_id
        JOIN tax_benefit_model_versions AS model_version
          ON model_version.id = parameter.tax_benefit_model_version_id
        JOIN tax_benefit_models AS model ON model.id = model_version.model_id
        JOIN stage_catalog_models AS source
          ON source.name = model.name AND source.version = model_version.version
        WHERE source.country_id = :country_id
          AND parameter_value.policy_id IS NULL
          AND parameter_value.dynamic_id IS NULL
    ), differences AS (
        (SELECT * FROM staged EXCEPT SELECT * FROM actual)
        UNION ALL
        (SELECT * FROM actual EXCEPT SELECT * FROM staged)
    ) SELECT EXISTS (SELECT 1 FROM differences)
    """,
)


VERSION_SCOPED_REFERENCE_DIFFERENCE_SQL = (
    """
    WITH staged AS (
        SELECT name, description, year, false AS is_output_dataset,
               NULL::text AS storage_path
        FROM stage_catalog_datasets
        WHERE country_id = :country_id
    ), actual AS (
        SELECT dataset.name, dataset.description, dataset.year,
               dataset.is_output_dataset, dataset.storage_path
        FROM datasets AS dataset
        JOIN tax_benefit_model_versions AS model_version
          ON model_version.id = dataset.tax_benefit_model_version_id
        JOIN tax_benefit_models AS model ON model.id = model_version.model_id
        JOIN stage_catalog_models AS source
          ON source.name = model.name AND source.version = model_version.version
        WHERE source.country_id = :country_id
          AND NOT dataset.is_output_dataset
          AND dataset.storage_path IS NULL
    ), differences AS (
        (SELECT * FROM staged EXCEPT SELECT * FROM actual)
        UNION ALL
        (SELECT * FROM actual EXCEPT SELECT * FROM staged)
    ) SELECT EXISTS (SELECT 1 FROM differences)
    """,
    """
    WITH staged AS (
        SELECT code, label, region_type, requires_filter, filter_field,
               filter_value, filter_strategy, parent_code, state_code,
               state_name, default_dataset_name
        FROM stage_catalog_regions
        WHERE country_id = :country_id
    ), actual AS (
        SELECT region.code, region.label, region.region_type::text,
               region.requires_filter, region.filter_field,
               region.filter_value, region.filter_strategy,
               region.parent_code, region.state_code, region.state_name,
               dataset.name
        FROM regions AS region
        JOIN tax_benefit_model_versions AS model_version
          ON model_version.id = region.tax_benefit_model_version_id
        JOIN tax_benefit_models AS model ON model.id = model_version.model_id
        JOIN datasets AS dataset ON dataset.id = region.default_dataset_id
        JOIN stage_catalog_models AS source
          ON source.name = model.name AND source.version = model_version.version
        WHERE source.country_id = :country_id
    ), differences AS (
        (SELECT * FROM staged EXCEPT SELECT * FROM actual)
        UNION ALL
        (SELECT * FROM actual EXCEPT SELECT * FROM staged)
    ) SELECT EXISTS (SELECT 1 FROM differences)
    """,
)


def _assert_country_matches(connection: Connection, country_id: str) -> None:
    statements = (
        MODEL_DIFFERENCE_SQL,
        *VERSIONED_DIFFERENCE_SQL,
        *VERSION_SCOPED_REFERENCE_DIFFERENCE_SQL,
    )
    for statement in statements:
        differs = connection.execute(
            text(statement),
            {"country_id": country_id},
        ).scalar_one()
        if differs:
            raise CatalogPublicationError(
                f"persisted {country_id} catalog differs from PolicyEngine.py"
            )


def _reject_dataset_role_conflicts(
    connection: Connection,
    country_id: str,
) -> None:
    conflict = connection.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM stage_catalog_datasets AS source_dataset
                JOIN stage_catalog_models AS source_model
                  ON source_model.country_id = source_dataset.country_id
                JOIN tax_benefit_models AS model
                  ON model.name = source_model.name
                JOIN tax_benefit_model_versions AS model_version
                  ON model_version.model_id = model.id
                 AND model_version.version = source_model.version
                JOIN datasets AS dataset
                  ON dataset.tax_benefit_model_version_id = model_version.id
                 AND dataset.name = source_dataset.name
                WHERE source_dataset.country_id = :country_id
                  AND (
                      dataset.is_output_dataset
                      OR dataset.storage_path IS NOT NULL
                  )
            )
            """
        ),
        {"country_id": country_id},
    ).scalar_one()
    if conflict:
        raise CatalogPublicationError(
            f"persisted {country_id} dataset identity is not an input dataset"
        )


INSERT_MODEL_SQL = """
INSERT INTO tax_benefit_models (
    id, created_at, updated_at, name, description
)
SELECT id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, name, description
FROM stage_catalog_models
WHERE country_id = :country_id
ON CONFLICT (name) DO NOTHING
"""

INSERT_MODEL_VERSION_SQL = """
INSERT INTO tax_benefit_model_versions (
    id, created_at, model_id, version, description, current_law_id,
    metadata_time_periods
)
SELECT source.version_id, CURRENT_TIMESTAMP, model.id,
       source.version, source.version_description, source.current_law_id,
       source.metadata_time_periods::json
FROM stage_catalog_models AS source
JOIN tax_benefit_models AS model ON model.name = source.name
WHERE source.country_id = :country_id
"""

INSERT_DATASETS_SQL = """
INSERT INTO datasets (
    id, created_at, updated_at, name, description, storage_path, year,
    is_output_dataset, tax_benefit_model_version_id
)
SELECT source_dataset.id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
       source_dataset.name, source_dataset.description, NULL,
       source_dataset.year, false, model_version.id
FROM stage_catalog_datasets AS source_dataset
JOIN stage_catalog_models AS source_model
  ON source_model.country_id = source_dataset.country_id
JOIN tax_benefit_models AS model ON model.name = source_model.name
JOIN tax_benefit_model_versions AS model_version
  ON model_version.model_id = model.id
 AND model_version.version = source_model.version
WHERE source_dataset.country_id = :country_id
"""

INSERT_VARIABLES_SQL = """
INSERT INTO variables (
    id, created_at, name, label, entity, description, data_type,
    possible_values, default_value, adds, subtracts,
    tax_benefit_model_version_id
)
SELECT source_variable.id, CURRENT_TIMESTAMP, source_variable.name,
       source_variable.label, source_variable.entity,
       source_variable.description, source_variable.data_type,
       source_variable.possible_values::json,
       source_variable.default_value::json,
       source_variable.adds::json, source_variable.subtracts::json,
       model_version.id
FROM stage_catalog_variables AS source_variable
JOIN stage_catalog_models AS source_model
  ON source_model.country_id = source_variable.country_id
JOIN tax_benefit_models AS model ON model.name = source_model.name
JOIN tax_benefit_model_versions AS model_version
  ON model_version.model_id = model.id
 AND model_version.version = source_model.version
WHERE source_variable.country_id = :country_id
"""

INSERT_PARAMETER_NODES_SQL = """
INSERT INTO parameter_nodes (
    id, created_at, name, label, description, tax_benefit_model_version_id
)
SELECT source_node.id, CURRENT_TIMESTAMP, source_node.name,
       source_node.label, source_node.description, model_version.id
FROM stage_catalog_parameter_nodes AS source_node
JOIN stage_catalog_models AS source_model
  ON source_model.country_id = source_node.country_id
JOIN tax_benefit_models AS model ON model.name = source_model.name
JOIN tax_benefit_model_versions AS model_version
  ON model_version.model_id = model.id
 AND model_version.version = source_model.version
WHERE source_node.country_id = :country_id
"""

INSERT_PARAMETERS_SQL = """
INSERT INTO parameters (
    id, created_at, name, label, description, data_type, unit,
    tax_benefit_model_version_id
)
SELECT source_parameter.id, CURRENT_TIMESTAMP, source_parameter.name,
       source_parameter.label, source_parameter.description,
       source_parameter.data_type, source_parameter.unit, model_version.id
FROM stage_catalog_parameters AS source_parameter
JOIN stage_catalog_models AS source_model
  ON source_model.country_id = source_parameter.country_id
JOIN tax_benefit_models AS model ON model.name = source_model.name
JOIN tax_benefit_model_versions AS model_version
  ON model_version.model_id = model.id
 AND model_version.version = source_model.version
WHERE source_parameter.country_id = :country_id
"""

INSERT_PARAMETER_VALUES_SQL = """
INSERT INTO parameter_values (
    id, created_at, parameter_id, value_json, start_date, end_date,
    policy_id, dynamic_id
)
SELECT source_value.id, CURRENT_TIMESTAMP, parameter.id,
       source_value.value_json::json, source_value.start_date,
       source_value.end_date, NULL, NULL
FROM stage_catalog_parameter_values AS source_value
JOIN stage_catalog_models AS source_model
  ON source_model.country_id = source_value.country_id
JOIN tax_benefit_models AS model ON model.name = source_model.name
JOIN tax_benefit_model_versions AS model_version
  ON model_version.model_id = model.id
 AND model_version.version = source_model.version
JOIN parameters AS parameter
  ON parameter.tax_benefit_model_version_id = model_version.id
 AND parameter.name = source_value.parameter_name
WHERE source_value.country_id = :country_id
"""

INSERT_REGIONS_SQL = """
INSERT INTO regions (
    id, created_at, updated_at, code, label, region_type, requires_filter,
    filter_field, filter_value, filter_strategy, parent_code, state_code,
    state_name, tax_benefit_model_version_id, default_dataset_id
)
SELECT source_region.id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
       source_region.code, source_region.label,
       source_region.region_type::v2_region_type,
       source_region.requires_filter, source_region.filter_field,
       source_region.filter_value, source_region.filter_strategy,
       source_region.parent_code, source_region.state_code,
       source_region.state_name, model_version.id, dataset.id
FROM stage_catalog_regions AS source_region
JOIN stage_catalog_models AS source_model
  ON source_model.country_id = source_region.country_id
JOIN tax_benefit_models AS model ON model.name = source_model.name
JOIN tax_benefit_model_versions AS model_version
  ON model_version.model_id = model.id
 AND model_version.version = source_model.version
JOIN datasets AS dataset
  ON dataset.tax_benefit_model_version_id = model_version.id
 AND dataset.name = source_region.default_dataset_name
WHERE source_region.country_id = :country_id
"""


SET_BASED_INSERT_SQL = (
    INSERT_MODEL_SQL,
    INSERT_MODEL_VERSION_SQL,
    INSERT_DATASETS_SQL,
    INSERT_VARIABLES_SQL,
    INSERT_PARAMETER_NODES_SQL,
    INSERT_PARAMETERS_SQL,
    INSERT_PARAMETER_VALUES_SQL,
    INSERT_REGIONS_SQL,
)


def _publish_new_country(connection: Connection, country_id: str) -> None:
    _reject_dataset_role_conflicts(connection, country_id)
    for statement in SET_BASED_INSERT_SQL:
        connection.execute(text(statement), {"country_id": country_id})


def _assert_canonical_value_uniqueness(connection: Connection) -> None:
    duplicates = connection.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM parameter_values
                WHERE policy_id IS NULL AND dynamic_id IS NULL
                GROUP BY parameter_id, start_date
                HAVING count(*) > 1
            )
            """
        )
    ).scalar_one()
    if duplicates:
        raise CatalogPublicationError(
            "canonical parameter-value uniqueness validation failed"
        )


def publish_catalog(
    engine: Engine,
    catalog: NormalizedCatalog,
    *,
    checkpoint: Callable[[str, Connection], None] | None = None,
) -> PublicationEvidence:
    """Publish one complete catalog atomically and return non-secret evidence."""

    started = time.monotonic()
    with engine.begin() as connection:
        _verify_expected_revision(connection)
        _acquire_publication_lock(connection)
        before = _protected_row_counts(connection)
        _create_staging_tables(connection)
        _stage_catalog(connection, catalog, checkpoint=checkpoint)
        if checkpoint is not None:
            checkpoint("after_copy", connection)

        existing: set[str] = set()
        for country in catalog.countries:
            if _version_exists(connection, country.country_id):
                _assert_country_matches(connection, country.country_id)
                existing.add(country.country_id)

        for country in catalog.countries:
            if country.country_id not in existing:
                _publish_new_country(connection, country.country_id)
        if checkpoint is not None:
            checkpoint("after_reconciliation", connection)

        for country in catalog.countries:
            _assert_country_matches(connection, country.country_id)
        _assert_canonical_value_uniqueness(connection)
        if _protected_row_counts(connection) != before:
            raise CatalogPublicationError(
                "publication changed simulation, report, or dataset-version rows"
            )
        if checkpoint is not None:
            checkpoint("after_validation", connection)

    fallback_summaries = tuple(
        (country.country_id, summary.region_type, summary.count)
        for country in catalog.countries
        for summary in country.fallback_summaries
    )
    _log_fallback_warning(fallback_summaries)
    return PublicationEvidence(
        policyengine_version=catalog.policyengine_version,
        dependency_versions=catalog.dependency_versions,
        entity_counts=catalog.entity_counts(),
        fallback_summaries=fallback_summaries,
        elapsed_seconds=time.monotonic() - started,
    )


def _log_fallback_warning(
    fallback_summaries: tuple[tuple[str, str, int], ...],
) -> None:
    if not fallback_summaries:
        return
    LOGGER.warning(
        "PolicyEngine.py regional dataset fallback summary: %s",
        fallback_summaries,
    )
