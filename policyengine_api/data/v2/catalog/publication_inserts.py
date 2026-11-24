"""Set-based inserts that publish one staged country into the v2 catalog tables."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlmodel import col

from policyengine_api.data.v2.catalog.publication_staging_base import (
    StagedDataset,
    StagedModel,
    StagedParameter,
    StagedParameterNode,
    StagedParameterValue,
    StagedRegion,
    StagedVariable,
)
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

if TYPE_CHECKING:
    from sqlalchemy.orm import Mapper
    from sqlalchemy.types import TypeEngine
    from sqlmodel import Session, SQLModel

    from policyengine_api.data.v2.catalog.records import CountryCatalog

COUNTRY_ID: sa.BindParameter[str] = sa.bindparam("country_id")
# How a Session runs these statements: as written, with the country as their
# one parameter. Given parameters, an ORM INSERT otherwise takes them for rows
# to insert (its bulk strategy).
RAW_DML_STRATEGY: dict[str, Any] = {"dml_strategy": "raw"}


def column_type(model: type[SQLModel], column_name: str) -> TypeEngine[Any]:
    """Return the SQL type of one column of a mapped class's table."""
    mapper: Mapper[Any] = sa.inspect(model)
    return mapper.columns[column_name].type


INSERT_MODEL = (
    postgresql_insert(TaxBenefitModel)
    .from_select(
        ["id", "created_at", "updated_at", "name", "description"],
        sa.select(
            col(StagedModel.id),
            sa.func.current_timestamp(),
            sa.func.current_timestamp(),
            col(StagedModel.name),
            col(StagedModel.description),
        ).where(col(StagedModel.country_id) == COUNTRY_ID),
    )
    .on_conflict_do_nothing(index_elements=[col(TaxBenefitModel.name)])
)

INSERT_MODEL_VERSION = sa.insert(TaxBenefitModelVersion).from_select(
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
        col(StagedModel.version_id),
        sa.func.current_timestamp(),
        col(TaxBenefitModel.id),
        col(StagedModel.version),
        col(StagedModel.version_description),
        col(StagedModel.current_law_id),
        sa.cast(
            col(StagedModel.metadata_time_periods),
            column_type(TaxBenefitModelVersion, "metadata_time_periods"),
        ),
        col(StagedModel.catalog_format),
        sa.cast(
            col(StagedModel.entities), column_type(TaxBenefitModelVersion, "entities")
        ),
        sa.cast(
            col(StagedModel.basic_inputs),
            column_type(TaxBenefitModelVersion, "basic_inputs"),
        ),
    )
    .select_from(
        sa.join(
            StagedModel,
            TaxBenefitModel,
            col(TaxBenefitModel.name) == col(StagedModel.name),
        )
    )
    .where(col(StagedModel.country_id) == COUNTRY_ID),
)

INSERT_DATASETS = sa.insert(Dataset).from_select(
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
        col(StagedDataset.id),
        sa.func.current_timestamp(),
        sa.func.current_timestamp(),
        col(StagedDataset.name),
        col(StagedDataset.description),
        sa.cast(sa.null(), column_type(Dataset, "storage_path")),
        col(StagedDataset.year),
        sa.literal(value=False),
        col(TaxBenefitModelVersion.id),
    )
    .select_from(
        sa.join(
            StagedDataset,
            StagedModel,
            col(StagedModel.country_id) == col(StagedDataset.country_id),
        )
        .join(TaxBenefitModel, col(TaxBenefitModel.name) == col(StagedModel.name))
        .join(
            TaxBenefitModelVersion,
            sa.and_(
                col(TaxBenefitModelVersion.model_id) == col(TaxBenefitModel.id),
                col(TaxBenefitModelVersion.version) == col(StagedModel.version),
            ),
        )
    )
    .where(col(StagedDataset.country_id) == COUNTRY_ID),
)

INSERT_VARIABLES = sa.insert(Variable).from_select(
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
        col(StagedVariable.id),
        sa.func.current_timestamp(),
        col(StagedVariable.name),
        col(StagedVariable.label),
        col(StagedVariable.entity),
        col(StagedVariable.description),
        col(StagedVariable.data_type),
        sa.cast(
            col(StagedVariable.possible_values),
            column_type(Variable, "possible_values"),
        ),
        sa.cast(
            col(StagedVariable.default_value),
            column_type(Variable, "default_value"),
        ),
        sa.cast(col(StagedVariable.adds), column_type(Variable, "adds")),
        sa.cast(
            col(StagedVariable.subtracts),
            column_type(Variable, "subtracts"),
        ),
        col(StagedVariable.is_input_variable),
        col(StagedVariable.hidden_input),
        col(StagedVariable.module_name),
        col(StagedVariable.adds_parameter_path),
        col(StagedVariable.subtracts_parameter_path),
        sa.cast(
            col(StagedVariable.enum_values),
            column_type(Variable, "enum_values"),
        ),
        col(StagedVariable.unit),
        col(StagedVariable.definition_period),
        col(TaxBenefitModelVersion.id),
    )
    .select_from(
        sa.join(
            StagedVariable,
            StagedModel,
            col(StagedModel.country_id) == col(StagedVariable.country_id),
        )
        .join(TaxBenefitModel, col(TaxBenefitModel.name) == col(StagedModel.name))
        .join(
            TaxBenefitModelVersion,
            sa.and_(
                col(TaxBenefitModelVersion.model_id) == col(TaxBenefitModel.id),
                col(TaxBenefitModelVersion.version) == col(StagedModel.version),
            ),
        )
    )
    .where(col(StagedVariable.country_id) == COUNTRY_ID),
)

INSERT_PARAMETER_NODES = sa.insert(ParameterNode).from_select(
    [
        "id",
        "created_at",
        "name",
        "label",
        "description",
        "tax_benefit_model_version_id",
    ],
    sa.select(
        col(StagedParameterNode.id),
        sa.func.current_timestamp(),
        col(StagedParameterNode.name),
        col(StagedParameterNode.label),
        col(StagedParameterNode.description),
        col(TaxBenefitModelVersion.id),
    )
    .select_from(
        sa.join(
            StagedParameterNode,
            StagedModel,
            col(StagedModel.country_id) == col(StagedParameterNode.country_id),
        )
        .join(TaxBenefitModel, col(TaxBenefitModel.name) == col(StagedModel.name))
        .join(
            TaxBenefitModelVersion,
            sa.and_(
                col(TaxBenefitModelVersion.model_id) == col(TaxBenefitModel.id),
                col(TaxBenefitModelVersion.version) == col(StagedModel.version),
            ),
        )
    )
    .where(col(StagedParameterNode.country_id) == COUNTRY_ID),
)

INSERT_PARAMETERS = sa.insert(Parameter).from_select(
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
        col(StagedParameter.id),
        sa.func.current_timestamp(),
        col(StagedParameter.name),
        col(StagedParameter.label),
        col(StagedParameter.description),
        col(StagedParameter.data_type),
        col(StagedParameter.unit),
        col(StagedParameter.economy),
        col(StagedParameter.household),
        col(TaxBenefitModelVersion.id),
    )
    .select_from(
        sa.join(
            StagedParameter,
            StagedModel,
            col(StagedModel.country_id) == col(StagedParameter.country_id),
        )
        .join(TaxBenefitModel, col(TaxBenefitModel.name) == col(StagedModel.name))
        .join(
            TaxBenefitModelVersion,
            sa.and_(
                col(TaxBenefitModelVersion.model_id) == col(TaxBenefitModel.id),
                col(TaxBenefitModelVersion.version) == col(StagedModel.version),
            ),
        )
    )
    .where(col(StagedParameter.country_id) == COUNTRY_ID),
)

INSERT_PARAMETER_VALUES = sa.insert(ParameterValue).from_select(
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
        col(StagedParameterValue.id),
        sa.func.current_timestamp(),
        col(Parameter.id),
        sa.cast(
            col(StagedParameterValue.value_json),
            column_type(ParameterValue, "value_json"),
        ),
        col(StagedParameterValue.start_date),
        col(StagedParameterValue.end_date),
        sa.cast(sa.null(), column_type(ParameterValue, "policy_id")),
        sa.cast(sa.null(), column_type(ParameterValue, "dynamic_id")),
    )
    .select_from(
        sa.join(
            StagedParameterValue,
            StagedModel,
            col(StagedModel.country_id) == col(StagedParameterValue.country_id),
        )
        .join(TaxBenefitModel, col(TaxBenefitModel.name) == col(StagedModel.name))
        .join(
            TaxBenefitModelVersion,
            sa.and_(
                col(TaxBenefitModelVersion.model_id) == col(TaxBenefitModel.id),
                col(TaxBenefitModelVersion.version) == col(StagedModel.version),
            ),
        )
        .join(
            Parameter,
            sa.and_(
                col(Parameter.tax_benefit_model_version_id)
                == col(TaxBenefitModelVersion.id),
                col(Parameter.name) == col(StagedParameterValue.parameter_name),
            ),
        )
    )
    .where(col(StagedParameterValue.country_id) == COUNTRY_ID),
)

INSERT_REGIONS = sa.insert(Region).from_select(
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
        col(StagedRegion.id),
        sa.func.current_timestamp(),
        sa.func.current_timestamp(),
        col(StagedRegion.code),
        col(StagedRegion.label),
        sa.cast(col(StagedRegion.region_type), column_type(Region, "region_type")),
        col(StagedRegion.requires_filter),
        col(StagedRegion.filter_field),
        col(StagedRegion.filter_value),
        col(StagedRegion.filter_strategy),
        col(StagedRegion.parent_code),
        col(StagedRegion.state_code),
        col(StagedRegion.state_name),
        col(TaxBenefitModelVersion.id),
        col(Dataset.id),
    )
    .select_from(
        sa.join(
            StagedRegion,
            StagedModel,
            col(StagedModel.country_id) == col(StagedRegion.country_id),
        )
        .join(TaxBenefitModel, col(TaxBenefitModel.name) == col(StagedModel.name))
        .join(
            TaxBenefitModelVersion,
            sa.and_(
                col(TaxBenefitModelVersion.model_id) == col(TaxBenefitModel.id),
                col(TaxBenefitModelVersion.version) == col(StagedModel.version),
            ),
        )
        .join(
            Dataset,
            sa.and_(
                col(Dataset.tax_benefit_model_version_id)
                == col(TaxBenefitModelVersion.id),
                col(Dataset.name) == col(StagedRegion.default_dataset_name),
            ),
        )
    )
    .where(col(StagedRegion.country_id) == COUNTRY_ID),
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


def publish_new_country(session: Session, country: CountryCatalog) -> None:
    """Insert one country's staged catalog into the v2 tables, parents first.

    The model row is reused if one with the same name already exists. Each
    statement is one ``INSERT ... SELECT`` from the staging tables, so no row
    passes through Python.
    """
    for statement in SET_BASED_INSERT_STATEMENTS:
        session.execute(
            statement,
            {"country_id": country.country_id},
            execution_options=RAW_DML_STRATEGY,
        )
