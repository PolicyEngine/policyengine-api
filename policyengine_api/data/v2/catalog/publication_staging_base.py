"""The temporary staging tables catalog publication COPYs a catalog into.

Each table is a SQLModel class on ``StagingBase``, whose own registry keeps
them out of the v2 metadata (``V2_METADATA``) that Alembic compares with the
database: they are not persistent schema. Every one is TEMPORARY with ON COMMIT
DROP, so publication creates them in its transaction
(``publication_staging.create_staging_tables``) and PostgreSQL drops them when
it commits or rolls back. ``test_publication_staging_tables_are_temporary_and_
dropped_at_commit`` checks every table.

Each class declares its columns in the order publication COPYs them, which is
the order of the rows ``publication_staging`` builds. Publication inserts the
staged rows into the catalog tables with ``INSERT ... SELECT``
(``publication_inserts``) and compares them with stored versions
(``publication_reconciliation``).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import registry
from sqlmodel import Field, SQLModel

# PostgreSQL's TIMESTAMP WITH TIME ZONE. SQLModel's Field annotates sa_type as a
# type class, but a timezone-aware DateTime is an instance of one.
TIMESTAMP_WITH_TIME_ZONE: Any = sa.DateTime(timezone=True)
# What makes each staging table temporary, dropped when the transaction ends.
TEMPORARY_UNTIL_COMMIT: dict[str, Any] = {
    "prefixes": ["TEMPORARY"],
    "postgresql_on_commit": "DROP",
}


class StagingBase(SQLModel, registry=registry()):
    """The declarative base of the staging tables, on a registry of their own."""


STAGING_METADATA = StagingBase.metadata


class StagedModel(StagingBase, table=True):
    """A country's model and model version, one row per country."""

    __tablename__ = "stage_catalog_models"
    __table_args__ = TEMPORARY_UNTIL_COMMIT

    country_id: str = Field(sa_type=sa.Text, primary_key=True)
    id: UUID = Field(sa_type=sa.Uuid)
    name: str = Field(sa_type=sa.Text)
    description: str | None = Field(default=None, sa_type=sa.Text)
    version_id: UUID = Field(sa_type=sa.Uuid)
    version: str = Field(sa_type=sa.Text)
    version_description: str | None = Field(default=None, sa_type=sa.Text)
    current_law_id: int = Field(sa_type=sa.Integer)
    metadata_time_periods: Any = Field(sa_type=JSONB, nullable=False)
    catalog_format: int = Field(sa_type=sa.Integer)
    entities: Any = Field(sa_type=JSONB, nullable=False)
    basic_inputs: Any = Field(sa_type=JSONB, nullable=False)


class StagedVariable(StagingBase, table=True):
    """One variable of a country's catalog."""

    __tablename__ = "stage_catalog_variables"
    __table_args__ = TEMPORARY_UNTIL_COMMIT

    country_id: str = Field(sa_type=sa.Text, primary_key=True)
    id: UUID = Field(sa_type=sa.Uuid)
    name: str = Field(sa_type=sa.Text, primary_key=True)
    label: str | None = Field(default=None, sa_type=sa.Text)
    entity: str = Field(sa_type=sa.Text)
    description: str | None = Field(default=None, sa_type=sa.Text)
    data_type: str | None = Field(default=None, sa_type=sa.Text)
    possible_values: Any = Field(default=None, sa_type=JSONB, nullable=True)
    default_value: Any = Field(sa_type=JSONB, nullable=False)
    adds: Any = Field(default=None, sa_type=JSONB, nullable=True)
    subtracts: Any = Field(default=None, sa_type=JSONB, nullable=True)
    is_input_variable: bool | None = Field(default=None, sa_type=sa.Boolean)
    hidden_input: bool | None = Field(default=None, sa_type=sa.Boolean)
    module_name: str | None = Field(default=None, sa_type=sa.Text)
    adds_parameter_path: str | None = Field(default=None, sa_type=sa.Text)
    subtracts_parameter_path: str | None = Field(default=None, sa_type=sa.Text)
    enum_values: Any = Field(default=None, sa_type=JSONB, nullable=True)
    unit: str | None = Field(default=None, sa_type=sa.Text)
    definition_period: str | None = Field(default=None, sa_type=sa.Text)


class StagedParameterNode(StagingBase, table=True):
    """One parameter node of a country's catalog."""

    __tablename__ = "stage_catalog_parameter_nodes"
    __table_args__ = TEMPORARY_UNTIL_COMMIT

    country_id: str = Field(sa_type=sa.Text, primary_key=True)
    id: UUID = Field(sa_type=sa.Uuid)
    name: str = Field(sa_type=sa.Text, primary_key=True)
    label: str | None = Field(default=None, sa_type=sa.Text)
    description: str | None = Field(default=None, sa_type=sa.Text)


class StagedParameter(StagingBase, table=True):
    """One parameter of a country's catalog."""

    __tablename__ = "stage_catalog_parameters"
    __table_args__ = TEMPORARY_UNTIL_COMMIT

    country_id: str = Field(sa_type=sa.Text, primary_key=True)
    id: UUID = Field(sa_type=sa.Uuid)
    name: str = Field(sa_type=sa.Text, primary_key=True)
    label: str | None = Field(default=None, sa_type=sa.Text)
    description: str | None = Field(default=None, sa_type=sa.Text)
    data_type: str | None = Field(default=None, sa_type=sa.Text)
    unit: str | None = Field(default=None, sa_type=sa.Text)
    economy: bool = Field(sa_type=sa.Boolean)
    household: bool = Field(sa_type=sa.Boolean)


class StagedParameterValue(StagingBase, table=True):
    """One current-law value of a parameter, named by the parameter's name."""

    __tablename__ = "stage_catalog_parameter_values"
    __table_args__ = TEMPORARY_UNTIL_COMMIT

    country_id: str = Field(sa_type=sa.Text, primary_key=True)
    parameter_name: str = Field(sa_type=sa.Text, primary_key=True)
    id: UUID = Field(sa_type=sa.Uuid)
    value_json: Any = Field(sa_type=JSONB, nullable=False)
    start_date: datetime = Field(sa_type=TIMESTAMP_WITH_TIME_ZONE, primary_key=True)
    end_date: datetime | None = Field(default=None, sa_type=TIMESTAMP_WITH_TIME_ZONE)


class StagedDataset(StagingBase, table=True):
    """One logical input dataset of a country's catalog."""

    __tablename__ = "stage_catalog_datasets"
    __table_args__ = TEMPORARY_UNTIL_COMMIT

    country_id: str = Field(sa_type=sa.Text, primary_key=True)
    id: UUID = Field(sa_type=sa.Uuid)
    name: str = Field(sa_type=sa.Text, primary_key=True)
    description: str | None = Field(default=None, sa_type=sa.Text)
    year: int = Field(sa_type=sa.Integer)


class StagedRegion(StagingBase, table=True):
    """One region of a country's catalog, naming its default dataset."""

    __tablename__ = "stage_catalog_regions"
    __table_args__ = TEMPORARY_UNTIL_COMMIT

    country_id: str = Field(sa_type=sa.Text, primary_key=True)
    id: UUID = Field(sa_type=sa.Uuid)
    code: str = Field(sa_type=sa.Text, primary_key=True)
    label: str = Field(sa_type=sa.Text)
    region_type: str = Field(sa_type=sa.Text)
    requires_filter: bool = Field(sa_type=sa.Boolean)
    filter_field: str | None = Field(default=None, sa_type=sa.Text)
    filter_value: str | None = Field(default=None, sa_type=sa.Text)
    filter_strategy: str | None = Field(default=None, sa_type=sa.Text)
    parent_code: str | None = Field(default=None, sa_type=sa.Text)
    state_code: str | None = Field(default=None, sa_type=sa.Text)
    state_name: str | None = Field(default=None, sa_type=sa.Text)
    default_dataset_name: str = Field(sa_type=sa.Text)


STAGING_MODELS = (
    StagedModel,
    StagedVariable,
    StagedParameterNode,
    StagedParameter,
    StagedParameterValue,
    StagedDataset,
    StagedRegion,
)
"""The staging tables, in the order publication COPYs each country into them."""
