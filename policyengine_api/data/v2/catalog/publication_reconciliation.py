"""Set-based reconciliation and validation for a staged v2 catalog."""

from __future__ import annotations

from sqlalchemy import Connection, text

from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)


def version_exists(connection: Connection, country_id: str) -> bool:
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


def assert_country_matches(connection: Connection, country_id: str) -> None:
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


def publish_new_country(connection: Connection, country_id: str) -> None:
    _reject_dataset_role_conflicts(connection, country_id)
    for statement in SET_BASED_INSERT_SQL:
        connection.execute(text(statement), {"country_id": country_id})


def assert_canonical_value_uniqueness(connection: Connection) -> None:
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
