"""Set-based reconciliation and validation for a staged v2 catalog."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import Connection, Select
from sqlalchemy.dialects.postgresql import JSONB, insert as postgresql_insert

from policyengine_api.data.v2.catalog.publication_staging import (
    STAGE_CATALOG_DATASETS,
    STAGE_CATALOG_MODELS,
    STAGE_CATALOG_PARAMETER_NODES,
    STAGE_CATALOG_PARAMETER_VALUES,
    STAGE_CATALOG_PARAMETERS,
    STAGE_CATALOG_REGIONS,
    STAGE_CATALOG_VARIABLES,
)
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)
from policyengine_api.data.v2.catalog.records import CountryCatalog
from policyengine_api.data.v2.models import (
    Dataset,
    Parameter,
    ParameterNode,
    ParameterValue,
    Region,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    Variable,
)


DATASETS = Dataset.__table__
MODELS = TaxBenefitModel.__table__
MODEL_VERSIONS = TaxBenefitModelVersion.__table__
PARAMETERS = Parameter.__table__
PARAMETER_NODES = ParameterNode.__table__
PARAMETER_VALUES = ParameterValue.__table__
REGIONS = Region.__table__
VARIABLES = Variable.__table__

COUNTRY_ID = sa.bindparam("country_id")


def version_exists(connection: Connection, country: CountryCatalog) -> bool:
    statement = (
        sa.select(MODEL_VERSIONS.c.id)
        .select_from(
            MODEL_VERSIONS.join(
                MODELS,
                MODELS.c.id == MODEL_VERSIONS.c.model_id,
            )
        )
        .where(
            MODELS.c.name == country.model.name,
            MODEL_VERSIONS.c.version == country.model_version.version,
        )
        .limit(1)
    )
    return connection.execute(statement).first() is not None


def _versioned_table_from(table: sa.Table) -> sa.Join:
    return table.join(
        MODEL_VERSIONS,
        MODEL_VERSIONS.c.id == table.c.tax_benefit_model_version_id,
    ).join(
        MODELS,
        MODELS.c.id == MODEL_VERSIONS.c.model_id,
    )


def _comparison_pairs(
    country: CountryCatalog,
) -> tuple[tuple[Select, Select], ...]:
    staged_country = STAGE_CATALOG_MODELS.c.country_id == country.country_id
    selected_version = sa.and_(
        MODELS.c.name == country.model.name,
        MODEL_VERSIONS.c.version == country.model_version.version,
    )

    staged_model_version = sa.select(
        STAGE_CATALOG_MODELS.c.version_description,
        STAGE_CATALOG_MODELS.c.current_law_id,
        STAGE_CATALOG_MODELS.c.metadata_time_periods,
    ).where(staged_country)
    actual_model_version = (
        sa.select(
            MODEL_VERSIONS.c.description,
            MODEL_VERSIONS.c.current_law_id,
            sa.cast(MODEL_VERSIONS.c.metadata_time_periods, JSONB),
        )
        .select_from(
            MODEL_VERSIONS.join(
                MODELS,
                MODELS.c.id == MODEL_VERSIONS.c.model_id,
            )
        )
        .where(selected_version)
    )

    staged_variables = sa.select(
        STAGE_CATALOG_VARIABLES.c.name,
        STAGE_CATALOG_VARIABLES.c.label,
        STAGE_CATALOG_VARIABLES.c.entity,
        STAGE_CATALOG_VARIABLES.c.description,
        STAGE_CATALOG_VARIABLES.c.data_type,
        STAGE_CATALOG_VARIABLES.c.possible_values,
        STAGE_CATALOG_VARIABLES.c.default_value,
        STAGE_CATALOG_VARIABLES.c.adds,
        STAGE_CATALOG_VARIABLES.c.subtracts,
    ).where(STAGE_CATALOG_VARIABLES.c.country_id == country.country_id)
    actual_variables = (
        sa.select(
            VARIABLES.c.name,
            VARIABLES.c.label,
            VARIABLES.c.entity,
            VARIABLES.c.description,
            VARIABLES.c.data_type,
            sa.cast(VARIABLES.c.possible_values, JSONB),
            sa.cast(VARIABLES.c.default_value, JSONB),
            sa.cast(VARIABLES.c.adds, JSONB),
            sa.cast(VARIABLES.c.subtracts, JSONB),
        )
        .select_from(_versioned_table_from(VARIABLES))
        .where(selected_version)
    )

    staged_parameter_nodes = sa.select(
        STAGE_CATALOG_PARAMETER_NODES.c.name,
        STAGE_CATALOG_PARAMETER_NODES.c.label,
        STAGE_CATALOG_PARAMETER_NODES.c.description,
    ).where(STAGE_CATALOG_PARAMETER_NODES.c.country_id == country.country_id)
    actual_parameter_nodes = (
        sa.select(
            PARAMETER_NODES.c.name,
            PARAMETER_NODES.c.label,
            PARAMETER_NODES.c.description,
        )
        .select_from(_versioned_table_from(PARAMETER_NODES))
        .where(selected_version)
    )

    staged_parameters = sa.select(
        STAGE_CATALOG_PARAMETERS.c.name,
        STAGE_CATALOG_PARAMETERS.c.label,
        STAGE_CATALOG_PARAMETERS.c.description,
        STAGE_CATALOG_PARAMETERS.c.data_type,
        STAGE_CATALOG_PARAMETERS.c.unit,
    ).where(STAGE_CATALOG_PARAMETERS.c.country_id == country.country_id)
    actual_parameters = (
        sa.select(
            PARAMETERS.c.name,
            PARAMETERS.c.label,
            PARAMETERS.c.description,
            PARAMETERS.c.data_type,
            PARAMETERS.c.unit,
        )
        .select_from(_versioned_table_from(PARAMETERS))
        .where(selected_version)
    )

    staged_parameter_values = sa.select(
        STAGE_CATALOG_PARAMETER_VALUES.c.parameter_name,
        STAGE_CATALOG_PARAMETER_VALUES.c.value_json,
        STAGE_CATALOG_PARAMETER_VALUES.c.start_date,
        STAGE_CATALOG_PARAMETER_VALUES.c.end_date,
    ).where(STAGE_CATALOG_PARAMETER_VALUES.c.country_id == country.country_id)
    actual_parameter_values = (
        sa.select(
            PARAMETERS.c.name,
            sa.cast(PARAMETER_VALUES.c.value_json, JSONB),
            PARAMETER_VALUES.c.start_date,
            PARAMETER_VALUES.c.end_date,
        )
        .select_from(
            PARAMETER_VALUES.join(
                PARAMETERS,
                PARAMETERS.c.id == PARAMETER_VALUES.c.parameter_id,
            )
            .join(
                MODEL_VERSIONS,
                MODEL_VERSIONS.c.id == PARAMETERS.c.tax_benefit_model_version_id,
            )
            .join(MODELS, MODELS.c.id == MODEL_VERSIONS.c.model_id)
        )
        .where(
            selected_version,
            PARAMETER_VALUES.c.policy_id.is_(None),
            PARAMETER_VALUES.c.dynamic_id.is_(None),
        )
    )

    staged_datasets = sa.select(
        STAGE_CATALOG_DATASETS.c.name,
        STAGE_CATALOG_DATASETS.c.description,
        STAGE_CATALOG_DATASETS.c.year,
        sa.literal(False),
        sa.cast(sa.null(), DATASETS.c.storage_path.type),
    ).where(STAGE_CATALOG_DATASETS.c.country_id == country.country_id)
    actual_datasets = (
        sa.select(
            DATASETS.c.name,
            DATASETS.c.description,
            DATASETS.c.year,
            DATASETS.c.is_output_dataset,
            DATASETS.c.storage_path,
        )
        .select_from(_versioned_table_from(DATASETS))
        .where(
            selected_version,
            DATASETS.c.is_output_dataset.is_(False),
            DATASETS.c.storage_path.is_(None),
        )
    )

    staged_regions = sa.select(
        STAGE_CATALOG_REGIONS.c.code,
        STAGE_CATALOG_REGIONS.c.label,
        STAGE_CATALOG_REGIONS.c.region_type,
        STAGE_CATALOG_REGIONS.c.requires_filter,
        STAGE_CATALOG_REGIONS.c.filter_field,
        STAGE_CATALOG_REGIONS.c.filter_value,
        STAGE_CATALOG_REGIONS.c.filter_strategy,
        STAGE_CATALOG_REGIONS.c.parent_code,
        STAGE_CATALOG_REGIONS.c.state_code,
        STAGE_CATALOG_REGIONS.c.state_name,
        STAGE_CATALOG_REGIONS.c.default_dataset_name,
    ).where(STAGE_CATALOG_REGIONS.c.country_id == country.country_id)
    actual_regions = (
        sa.select(
            REGIONS.c.code,
            REGIONS.c.label,
            sa.cast(REGIONS.c.region_type, sa.Text),
            REGIONS.c.requires_filter,
            REGIONS.c.filter_field,
            REGIONS.c.filter_value,
            REGIONS.c.filter_strategy,
            REGIONS.c.parent_code,
            REGIONS.c.state_code,
            REGIONS.c.state_name,
            DATASETS.c.name,
        )
        .select_from(
            _versioned_table_from(REGIONS).join(
                DATASETS,
                DATASETS.c.id == REGIONS.c.default_dataset_id,
            )
        )
        .where(selected_version)
    )

    return (
        (staged_model_version, actual_model_version),
        (staged_variables, actual_variables),
        (staged_parameter_nodes, actual_parameter_nodes),
        (staged_parameters, actual_parameters),
        (staged_parameter_values, actual_parameter_values),
        (staged_datasets, actual_datasets),
        (staged_regions, actual_regions),
    )


def _sets_differ(
    connection: Connection,
    staged: Select,
    actual: Select,
) -> bool:
    missing = sa.except_(staged, actual).subquery()
    extra = sa.except_(actual, staged).subquery()
    differences = sa.union_all(
        sa.select(sa.literal(1)).select_from(missing),
        sa.select(sa.literal(1)).select_from(extra),
    ).limit(1)
    return connection.execute(differences).first() is not None


def assert_country_matches(
    connection: Connection,
    country: CountryCatalog,
) -> None:
    for staged, actual in _comparison_pairs(country):
        if _sets_differ(connection, staged, actual):
            raise CatalogPublicationError(
                f"persisted {country.country_id} catalog differs from PolicyEngine.py"
            )


INSERT_MODEL = (
    postgresql_insert(MODELS)
    .from_select(
        ["id", "created_at", "updated_at", "name", "description"],
        sa.select(
            STAGE_CATALOG_MODELS.c.id,
            sa.func.current_timestamp(),
            sa.func.current_timestamp(),
            STAGE_CATALOG_MODELS.c.name,
            STAGE_CATALOG_MODELS.c.description,
        ).where(STAGE_CATALOG_MODELS.c.country_id == COUNTRY_ID),
    )
    .on_conflict_do_nothing(index_elements=[MODELS.c.name])
)

INSERT_MODEL_VERSION = sa.insert(MODEL_VERSIONS).from_select(
    [
        "id",
        "created_at",
        "model_id",
        "version",
        "description",
        "current_law_id",
        "metadata_time_periods",
    ],
    sa.select(
        STAGE_CATALOG_MODELS.c.version_id,
        sa.func.current_timestamp(),
        MODELS.c.id,
        STAGE_CATALOG_MODELS.c.version,
        STAGE_CATALOG_MODELS.c.version_description,
        STAGE_CATALOG_MODELS.c.current_law_id,
        sa.cast(
            STAGE_CATALOG_MODELS.c.metadata_time_periods,
            MODEL_VERSIONS.c.metadata_time_periods.type,
        ),
    )
    .select_from(
        STAGE_CATALOG_MODELS.join(
            MODELS,
            MODELS.c.name == STAGE_CATALOG_MODELS.c.name,
        )
    )
    .where(STAGE_CATALOG_MODELS.c.country_id == COUNTRY_ID),
)

INSERT_DATASETS = sa.insert(DATASETS).from_select(
    [
        "id",
        "created_at",
        "updated_at",
        "name",
        "description",
        "storage_path",
        "year",
        "is_output_dataset",
        "tax_benefit_model_version_id",
    ],
    sa.select(
        STAGE_CATALOG_DATASETS.c.id,
        sa.func.current_timestamp(),
        sa.func.current_timestamp(),
        STAGE_CATALOG_DATASETS.c.name,
        STAGE_CATALOG_DATASETS.c.description,
        sa.cast(sa.null(), DATASETS.c.storage_path.type),
        STAGE_CATALOG_DATASETS.c.year,
        sa.literal(False),
        MODEL_VERSIONS.c.id,
    )
    .select_from(
        STAGE_CATALOG_DATASETS.join(
            STAGE_CATALOG_MODELS,
            STAGE_CATALOG_MODELS.c.country_id == STAGE_CATALOG_DATASETS.c.country_id,
        )
        .join(MODELS, MODELS.c.name == STAGE_CATALOG_MODELS.c.name)
        .join(
            MODEL_VERSIONS,
            sa.and_(
                MODEL_VERSIONS.c.model_id == MODELS.c.id,
                MODEL_VERSIONS.c.version == STAGE_CATALOG_MODELS.c.version,
            ),
        )
    )
    .where(STAGE_CATALOG_DATASETS.c.country_id == COUNTRY_ID),
)

INSERT_VARIABLES = sa.insert(VARIABLES).from_select(
    [
        "id",
        "created_at",
        "name",
        "label",
        "entity",
        "description",
        "data_type",
        "possible_values",
        "default_value",
        "adds",
        "subtracts",
        "tax_benefit_model_version_id",
    ],
    sa.select(
        STAGE_CATALOG_VARIABLES.c.id,
        sa.func.current_timestamp(),
        STAGE_CATALOG_VARIABLES.c.name,
        STAGE_CATALOG_VARIABLES.c.label,
        STAGE_CATALOG_VARIABLES.c.entity,
        STAGE_CATALOG_VARIABLES.c.description,
        STAGE_CATALOG_VARIABLES.c.data_type,
        sa.cast(
            STAGE_CATALOG_VARIABLES.c.possible_values,
            VARIABLES.c.possible_values.type,
        ),
        sa.cast(
            STAGE_CATALOG_VARIABLES.c.default_value,
            VARIABLES.c.default_value.type,
        ),
        sa.cast(STAGE_CATALOG_VARIABLES.c.adds, VARIABLES.c.adds.type),
        sa.cast(
            STAGE_CATALOG_VARIABLES.c.subtracts,
            VARIABLES.c.subtracts.type,
        ),
        MODEL_VERSIONS.c.id,
    )
    .select_from(
        STAGE_CATALOG_VARIABLES.join(
            STAGE_CATALOG_MODELS,
            STAGE_CATALOG_MODELS.c.country_id == STAGE_CATALOG_VARIABLES.c.country_id,
        )
        .join(MODELS, MODELS.c.name == STAGE_CATALOG_MODELS.c.name)
        .join(
            MODEL_VERSIONS,
            sa.and_(
                MODEL_VERSIONS.c.model_id == MODELS.c.id,
                MODEL_VERSIONS.c.version == STAGE_CATALOG_MODELS.c.version,
            ),
        )
    )
    .where(STAGE_CATALOG_VARIABLES.c.country_id == COUNTRY_ID),
)

INSERT_PARAMETER_NODES = sa.insert(PARAMETER_NODES).from_select(
    [
        "id",
        "created_at",
        "name",
        "label",
        "description",
        "tax_benefit_model_version_id",
    ],
    sa.select(
        STAGE_CATALOG_PARAMETER_NODES.c.id,
        sa.func.current_timestamp(),
        STAGE_CATALOG_PARAMETER_NODES.c.name,
        STAGE_CATALOG_PARAMETER_NODES.c.label,
        STAGE_CATALOG_PARAMETER_NODES.c.description,
        MODEL_VERSIONS.c.id,
    )
    .select_from(
        STAGE_CATALOG_PARAMETER_NODES.join(
            STAGE_CATALOG_MODELS,
            STAGE_CATALOG_MODELS.c.country_id
            == STAGE_CATALOG_PARAMETER_NODES.c.country_id,
        )
        .join(MODELS, MODELS.c.name == STAGE_CATALOG_MODELS.c.name)
        .join(
            MODEL_VERSIONS,
            sa.and_(
                MODEL_VERSIONS.c.model_id == MODELS.c.id,
                MODEL_VERSIONS.c.version == STAGE_CATALOG_MODELS.c.version,
            ),
        )
    )
    .where(STAGE_CATALOG_PARAMETER_NODES.c.country_id == COUNTRY_ID),
)

INSERT_PARAMETERS = sa.insert(PARAMETERS).from_select(
    [
        "id",
        "created_at",
        "name",
        "label",
        "description",
        "data_type",
        "unit",
        "tax_benefit_model_version_id",
    ],
    sa.select(
        STAGE_CATALOG_PARAMETERS.c.id,
        sa.func.current_timestamp(),
        STAGE_CATALOG_PARAMETERS.c.name,
        STAGE_CATALOG_PARAMETERS.c.label,
        STAGE_CATALOG_PARAMETERS.c.description,
        STAGE_CATALOG_PARAMETERS.c.data_type,
        STAGE_CATALOG_PARAMETERS.c.unit,
        MODEL_VERSIONS.c.id,
    )
    .select_from(
        STAGE_CATALOG_PARAMETERS.join(
            STAGE_CATALOG_MODELS,
            STAGE_CATALOG_MODELS.c.country_id == STAGE_CATALOG_PARAMETERS.c.country_id,
        )
        .join(MODELS, MODELS.c.name == STAGE_CATALOG_MODELS.c.name)
        .join(
            MODEL_VERSIONS,
            sa.and_(
                MODEL_VERSIONS.c.model_id == MODELS.c.id,
                MODEL_VERSIONS.c.version == STAGE_CATALOG_MODELS.c.version,
            ),
        )
    )
    .where(STAGE_CATALOG_PARAMETERS.c.country_id == COUNTRY_ID),
)

INSERT_PARAMETER_VALUES = sa.insert(PARAMETER_VALUES).from_select(
    [
        "id",
        "created_at",
        "parameter_id",
        "value_json",
        "start_date",
        "end_date",
        "policy_id",
        "dynamic_id",
    ],
    sa.select(
        STAGE_CATALOG_PARAMETER_VALUES.c.id,
        sa.func.current_timestamp(),
        PARAMETERS.c.id,
        sa.cast(
            STAGE_CATALOG_PARAMETER_VALUES.c.value_json,
            PARAMETER_VALUES.c.value_json.type,
        ),
        STAGE_CATALOG_PARAMETER_VALUES.c.start_date,
        STAGE_CATALOG_PARAMETER_VALUES.c.end_date,
        sa.cast(sa.null(), PARAMETER_VALUES.c.policy_id.type),
        sa.cast(sa.null(), PARAMETER_VALUES.c.dynamic_id.type),
    )
    .select_from(
        STAGE_CATALOG_PARAMETER_VALUES.join(
            STAGE_CATALOG_MODELS,
            STAGE_CATALOG_MODELS.c.country_id
            == STAGE_CATALOG_PARAMETER_VALUES.c.country_id,
        )
        .join(MODELS, MODELS.c.name == STAGE_CATALOG_MODELS.c.name)
        .join(
            MODEL_VERSIONS,
            sa.and_(
                MODEL_VERSIONS.c.model_id == MODELS.c.id,
                MODEL_VERSIONS.c.version == STAGE_CATALOG_MODELS.c.version,
            ),
        )
        .join(
            PARAMETERS,
            sa.and_(
                PARAMETERS.c.tax_benefit_model_version_id == MODEL_VERSIONS.c.id,
                PARAMETERS.c.name == STAGE_CATALOG_PARAMETER_VALUES.c.parameter_name,
            ),
        )
    )
    .where(STAGE_CATALOG_PARAMETER_VALUES.c.country_id == COUNTRY_ID),
)

INSERT_REGIONS = sa.insert(REGIONS).from_select(
    [
        "id",
        "created_at",
        "updated_at",
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
        "tax_benefit_model_version_id",
        "default_dataset_id",
    ],
    sa.select(
        STAGE_CATALOG_REGIONS.c.id,
        sa.func.current_timestamp(),
        sa.func.current_timestamp(),
        STAGE_CATALOG_REGIONS.c.code,
        STAGE_CATALOG_REGIONS.c.label,
        sa.cast(STAGE_CATALOG_REGIONS.c.region_type, REGIONS.c.region_type.type),
        STAGE_CATALOG_REGIONS.c.requires_filter,
        STAGE_CATALOG_REGIONS.c.filter_field,
        STAGE_CATALOG_REGIONS.c.filter_value,
        STAGE_CATALOG_REGIONS.c.filter_strategy,
        STAGE_CATALOG_REGIONS.c.parent_code,
        STAGE_CATALOG_REGIONS.c.state_code,
        STAGE_CATALOG_REGIONS.c.state_name,
        MODEL_VERSIONS.c.id,
        DATASETS.c.id,
    )
    .select_from(
        STAGE_CATALOG_REGIONS.join(
            STAGE_CATALOG_MODELS,
            STAGE_CATALOG_MODELS.c.country_id == STAGE_CATALOG_REGIONS.c.country_id,
        )
        .join(MODELS, MODELS.c.name == STAGE_CATALOG_MODELS.c.name)
        .join(
            MODEL_VERSIONS,
            sa.and_(
                MODEL_VERSIONS.c.model_id == MODELS.c.id,
                MODEL_VERSIONS.c.version == STAGE_CATALOG_MODELS.c.version,
            ),
        )
        .join(
            DATASETS,
            sa.and_(
                DATASETS.c.tax_benefit_model_version_id == MODEL_VERSIONS.c.id,
                DATASETS.c.name == STAGE_CATALOG_REGIONS.c.default_dataset_name,
            ),
        )
    )
    .where(STAGE_CATALOG_REGIONS.c.country_id == COUNTRY_ID),
)

SET_BASED_INSERT_STATEMENTS = (
    INSERT_MODEL,
    INSERT_MODEL_VERSION,
    INSERT_DATASETS,
    INSERT_VARIABLES,
    INSERT_PARAMETER_NODES,
    INSERT_PARAMETERS,
    INSERT_PARAMETER_VALUES,
    INSERT_REGIONS,
)


def publish_new_country(connection: Connection, country: CountryCatalog) -> None:
    for statement in SET_BASED_INSERT_STATEMENTS:
        connection.execute(statement, {"country_id": country.country_id})


def assert_canonical_value_uniqueness(connection: Connection) -> None:
    duplicates = (
        sa.select(PARAMETER_VALUES.c.parameter_id)
        .where(
            PARAMETER_VALUES.c.policy_id.is_(None),
            PARAMETER_VALUES.c.dynamic_id.is_(None),
        )
        .group_by(
            PARAMETER_VALUES.c.parameter_id,
            PARAMETER_VALUES.c.start_date,
        )
        .having(sa.func.count() > 1)
        .limit(1)
    )
    if connection.execute(duplicates).first() is not None:
        raise CatalogPublicationError(
            "canonical parameter-value uniqueness validation failed"
        )
