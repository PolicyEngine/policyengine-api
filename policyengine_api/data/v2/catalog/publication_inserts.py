"""Set-based inserts that publish one staged country into the v2 catalog tables."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from policyengine_api.data.v2.catalog.publication_staging import (
    STAGE_CATALOG_DATASETS,
    STAGE_CATALOG_MODELS,
    STAGE_CATALOG_PARAMETER_NODES,
    STAGE_CATALOG_PARAMETER_VALUES,
    STAGE_CATALOG_PARAMETERS,
    STAGE_CATALOG_REGIONS,
    STAGE_CATALOG_VARIABLES,
)
from policyengine_api.data.v2.catalog.publication_tables import (
    DATASETS,
    MODEL_VERSIONS,
    MODELS,
    PARAMETER_NODES,
    PARAMETER_VALUES,
    PARAMETERS,
    REGIONS,
    VARIABLES,
)

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from policyengine_api.data.v2.catalog.records import CountryCatalog

COUNTRY_ID = sa.bindparam("country_id")


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
        "catalog_format",
        "entities",
        "basic_inputs",
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
        STAGE_CATALOG_MODELS.c.catalog_format,
        sa.cast(STAGE_CATALOG_MODELS.c.entities, MODEL_VERSIONS.c.entities.type),
        sa.cast(
            STAGE_CATALOG_MODELS.c.basic_inputs,
            MODEL_VERSIONS.c.basic_inputs.type,
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
        sa.literal(value=False),
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
        "is_input_variable",
        "hidden_input",
        "module_name",
        "adds_parameter_path",
        "subtracts_parameter_path",
        "enum_values",
        "unit",
        "definition_period",
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
        STAGE_CATALOG_VARIABLES.c.is_input_variable,
        STAGE_CATALOG_VARIABLES.c.hidden_input,
        STAGE_CATALOG_VARIABLES.c.module_name,
        STAGE_CATALOG_VARIABLES.c.adds_parameter_path,
        STAGE_CATALOG_VARIABLES.c.subtracts_parameter_path,
        sa.cast(
            STAGE_CATALOG_VARIABLES.c.enum_values,
            VARIABLES.c.enum_values.type,
        ),
        STAGE_CATALOG_VARIABLES.c.unit,
        STAGE_CATALOG_VARIABLES.c.definition_period,
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
        "economy",
        "household",
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
        STAGE_CATALOG_PARAMETERS.c.economy,
        STAGE_CATALOG_PARAMETERS.c.household,
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
    """Insert one country's staged catalog into the v2 tables, parents first.

    The model row is reused if one with the same name already exists.
    """
    for statement in SET_BASED_INSERT_STATEMENTS:
        connection.execute(statement, {"country_id": country.country_id})
