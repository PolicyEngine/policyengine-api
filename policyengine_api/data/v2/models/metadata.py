"""Canonical SQLModel tables for v2 model metadata, regions, and datasets."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Field, Relationship, SQLModel

from policyengine_api.data.v2.models.base import (
    IdentifiedModel,
    TimestampedModel,
    enum_type,
)

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.domain import Dynamic, Policy, Simulation
    from policyengine_api.data.v2.models.reports import Report


class RegionType(str, Enum):
    NATIONAL = "national"
    COUNTRY = "country"
    STATE = "state"
    CONGRESSIONAL_DISTRICT = "congressional_district"
    CONSTITUENCY = "constituency"
    LOCAL_AUTHORITY = "local_authority"
    CITY = "city"
    PLACE = "place"


class RegionDatasetLink(SQLModel, table=True):
    __tablename__ = "region_datasets"

    region_id: UUID = Field(
        foreign_key="regions.id",
        ondelete="CASCADE",
        primary_key=True,
    )
    dataset_id: UUID = Field(
        foreign_key="datasets.id",
        ondelete="CASCADE",
        primary_key=True,
    )


class TaxBenefitModel(TimestampedModel, table=True):
    __tablename__ = "tax_benefit_models"
    __table_args__ = (sa.UniqueConstraint("name", name="uq_tax_benefit_models_name"),)

    name: str = Field(max_length=32)
    description: str | None = None

    versions: list["TaxBenefitModelVersion"] = Relationship(
        back_populates="model",
        cascade_delete=True,
    )
    datasets: list["Dataset"] = Relationship(back_populates="tax_benefit_model")
    dataset_versions: list["DatasetVersion"] = Relationship(
        back_populates="tax_benefit_model"
    )
    regions: list["Region"] = Relationship(back_populates="tax_benefit_model")
    policies: list["Policy"] = Relationship(back_populates="tax_benefit_model")
    reports: list["Report"] = Relationship(back_populates="tax_benefit_model")


class TaxBenefitModelVersion(IdentifiedModel, table=True):
    __tablename__ = "tax_benefit_model_versions"
    __table_args__ = (
        sa.UniqueConstraint(
            "model_id",
            "version",
            name="uq_tax_benefit_model_versions_model_version",
        ),
    )

    model_id: UUID = Field(
        foreign_key="tax_benefit_models.id",
        ondelete="CASCADE",
        index=True,
    )
    version: str = Field(max_length=128)
    description: str | None = None

    model: TaxBenefitModel = Relationship(back_populates="versions")
    variables: list["Variable"] = Relationship(
        back_populates="tax_benefit_model_version",
        cascade_delete=True,
    )
    parameters: list["Parameter"] = Relationship(
        back_populates="tax_benefit_model_version",
        cascade_delete=True,
    )
    parameter_nodes: list["ParameterNode"] = Relationship(
        back_populates="tax_benefit_model_version",
        cascade_delete=True,
    )
    simulations: list["Simulation"] = Relationship(
        back_populates="tax_benefit_model_version"
    )


class Region(TimestampedModel, table=True):
    __tablename__ = "regions"
    __table_args__ = (
        sa.UniqueConstraint(
            "tax_benefit_model_id",
            "code",
            name="uq_regions_model_code",
        ),
        sa.CheckConstraint(
            "NOT requires_filter OR "
            "(filter_field IS NOT NULL AND filter_value IS NOT NULL)",
            name="ck_regions_required_filter_values",
        ),
    )

    code: str = Field(max_length=255)
    label: str = Field(max_length=255)
    region_type: RegionType = Field(sa_type=enum_type(RegionType, "v2_region_type"))
    requires_filter: bool = False
    filter_field: str | None = Field(default=None, max_length=128)
    filter_value: str | None = Field(default=None, max_length=255)
    filter_strategy: str | None = Field(default=None, max_length=64)
    parent_code: str | None = Field(default=None, max_length=255)
    state_code: str | None = Field(default=None, max_length=16)
    state_name: str | None = Field(default=None, max_length=128)
    tax_benefit_model_id: UUID = Field(
        foreign_key="tax_benefit_models.id",
        ondelete="RESTRICT",
        index=True,
    )

    tax_benefit_model: TaxBenefitModel = Relationship(back_populates="regions")
    datasets: list["Dataset"] = Relationship(
        back_populates="regions",
        link_model=RegionDatasetLink,
    )
    simulations: list["Simulation"] = Relationship(back_populates="region")
    reports: list["Report"] = Relationship(back_populates="region")


class Dataset(TimestampedModel, table=True):
    __tablename__ = "datasets"
    __table_args__ = (
        sa.UniqueConstraint(
            "tax_benefit_model_id",
            "name",
            "year",
            "is_output_dataset",
            name="uq_datasets_model_name_year_output",
        ),
        sa.CheckConstraint(
            "year BETWEEN 1900 AND 2200",
            name="ck_datasets_year",
        ),
    )

    name: str = Field(max_length=255)
    description: str | None = None
    storage_path: str = Field(max_length=1024)
    year: int
    is_output_dataset: bool = False
    tax_benefit_model_id: UUID = Field(
        foreign_key="tax_benefit_models.id",
        ondelete="RESTRICT",
        index=True,
    )

    tax_benefit_model: TaxBenefitModel = Relationship(back_populates="datasets")
    versions: list["DatasetVersion"] = Relationship(
        back_populates="dataset",
        cascade_delete=True,
    )
    regions: list[Region] = Relationship(
        back_populates="datasets",
        link_model=RegionDatasetLink,
    )
    input_simulations: list["Simulation"] = Relationship(
        back_populates="dataset",
        sa_relationship_kwargs={"foreign_keys": "Simulation.dataset_id"},
    )
    output_simulations: list["Simulation"] = Relationship(
        back_populates="output_dataset",
        sa_relationship_kwargs={"foreign_keys": "Simulation.output_dataset_id"},
    )
    reports: list["Report"] = Relationship(back_populates="dataset")


class DatasetVersion(IdentifiedModel, table=True):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        sa.UniqueConstraint(
            "dataset_id",
            "name",
            name="uq_dataset_versions_dataset_name",
        ),
    )

    name: str = Field(max_length=128)
    description: str | None = None
    dataset_id: UUID = Field(
        foreign_key="datasets.id",
        ondelete="CASCADE",
        index=True,
    )
    tax_benefit_model_id: UUID = Field(
        foreign_key="tax_benefit_models.id",
        ondelete="RESTRICT",
        index=True,
    )

    dataset: Dataset = Relationship(back_populates="versions")
    tax_benefit_model: TaxBenefitModel = Relationship(back_populates="dataset_versions")


class Variable(IdentifiedModel, table=True):
    __tablename__ = "variables"
    __table_args__ = (
        sa.UniqueConstraint(
            "tax_benefit_model_version_id",
            "name",
            name="uq_variables_model_version_name",
        ),
    )

    name: str = Field(max_length=512)
    label: str | None = Field(default=None, max_length=512)
    entity: str = Field(max_length=128)
    description: str | None = None
    data_type: str | None = Field(default=None, max_length=128)
    possible_values: list[str] | None = Field(default=None, sa_type=sa.JSON)
    default_value: Any = Field(default=None, sa_type=sa.JSON)
    adds: list[str] | None = Field(default=None, sa_type=sa.JSON)
    subtracts: list[str] | None = Field(default=None, sa_type=sa.JSON)
    tax_benefit_model_version_id: UUID = Field(
        foreign_key="tax_benefit_model_versions.id",
        ondelete="CASCADE",
        index=True,
    )

    tax_benefit_model_version: TaxBenefitModelVersion = Relationship(
        back_populates="variables"
    )


class ParameterNode(IdentifiedModel, table=True):
    __tablename__ = "parameter_nodes"
    __table_args__ = (
        sa.UniqueConstraint(
            "tax_benefit_model_version_id",
            "name",
            name="uq_parameter_nodes_model_version_name",
        ),
    )

    name: str = Field(max_length=512)
    label: str | None = Field(default=None, max_length=512)
    description: str | None = None
    tax_benefit_model_version_id: UUID = Field(
        foreign_key="tax_benefit_model_versions.id",
        ondelete="CASCADE",
        index=True,
    )

    tax_benefit_model_version: TaxBenefitModelVersion = Relationship(
        back_populates="parameter_nodes"
    )


class Parameter(IdentifiedModel, table=True):
    __tablename__ = "parameters"
    __table_args__ = (
        sa.UniqueConstraint(
            "tax_benefit_model_version_id",
            "name",
            name="uq_parameters_model_version_name",
        ),
    )

    name: str = Field(max_length=512)
    label: str | None = Field(default=None, max_length=512)
    description: str | None = None
    data_type: str | None = Field(default=None, max_length=128)
    unit: str | None = Field(default=None, max_length=128)
    tax_benefit_model_version_id: UUID = Field(
        foreign_key="tax_benefit_model_versions.id",
        ondelete="CASCADE",
        index=True,
    )

    tax_benefit_model_version: TaxBenefitModelVersion = Relationship(
        back_populates="parameters"
    )
    values: list["ParameterValue"] = Relationship(
        back_populates="parameter",
        cascade_delete=True,
    )


class ParameterValue(IdentifiedModel, table=True):
    __tablename__ = "parameter_values"
    __table_args__ = (
        sa.CheckConstraint(
            "policy_id IS NULL OR dynamic_id IS NULL",
            name="ck_parameter_values_single_owner",
        ),
        sa.Index(
            "ix_parameter_values_parameter_period",
            "parameter_id",
            "start_date",
            "end_date",
        ),
    )

    parameter_id: UUID = Field(
        foreign_key="parameters.id",
        ondelete="CASCADE",
    )
    value_json: Any = Field(sa_type=sa.JSON)
    start_date: datetime = Field(sa_type=sa.DateTime(timezone=True))
    end_date: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )
    policy_id: UUID | None = Field(
        default=None,
        foreign_key="policies.id",
        ondelete="CASCADE",
    )
    dynamic_id: UUID | None = Field(
        default=None,
        foreign_key="dynamics.id",
        ondelete="CASCADE",
    )

    parameter: Parameter = Relationship(back_populates="values")
    policy: Optional["Policy"] = Relationship(back_populates="parameter_values")
    dynamic: Optional["Dynamic"] = Relationship(back_populates="parameter_values")
