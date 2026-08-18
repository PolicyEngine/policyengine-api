"""Canonical SQLModel tables for v2 policies, households, and simulations."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import (
    IdentifiedModel,
    TimestampedModel,
    enum_type,
)
from policyengine_api.data.v2.models.metadata import (
    Dataset,
    Region,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.metadata import ParameterValue
    from policyengine_api.data.v2.models.reports import Report


class HouseholdJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SimulationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SimulationType(str, Enum):
    HOUSEHOLD = "household"
    ECONOMY = "economy"


class User(IdentifiedModel, table=True):
    __tablename__ = "users"
    __table_args__ = (
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint(
            "primary_country IN ('us', 'uk')",
            name="ck_users_primary_country",
        ),
    )

    first_name: str = Field(max_length=255)
    last_name: str = Field(max_length=255)
    email: str = Field(max_length=320, index=True)
    primary_country: str = Field(max_length=2)

    reports: list["Report"] = Relationship(back_populates="user")
    household_associations: list["UserHouseholdAssociation"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
    policy_associations: list["UserPolicy"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
    simulation_associations: list["UserSimulationAssociation"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )
    report_associations: list["UserReportAssociation"] = Relationship(
        back_populates="user",
        cascade_delete=True,
    )


class Policy(TimestampedModel, table=True):
    __tablename__ = "policies"

    name: str = Field(max_length=255)
    description: str | None = None
    tax_benefit_model_id: UUID = Field(
        foreign_key="tax_benefit_models.id",
        ondelete="RESTRICT",
        index=True,
    )

    tax_benefit_model: TaxBenefitModel = Relationship(back_populates="policies")
    parameter_values: list["ParameterValue"] = Relationship(
        back_populates="policy",
        cascade_delete=True,
    )
    simulations: list["Simulation"] = Relationship(back_populates="policy")
    household_jobs: list["HouseholdJob"] = Relationship(back_populates="policy")
    reports: list["Report"] = Relationship(back_populates="policy")
    user_associations: list["UserPolicy"] = Relationship(
        back_populates="policy",
        cascade_delete=True,
    )


class Dynamic(TimestampedModel, table=True):
    __tablename__ = "dynamics"

    name: str = Field(max_length=255)
    description: str | None = None

    parameter_values: list["ParameterValue"] = Relationship(
        back_populates="dynamic",
        cascade_delete=True,
    )
    simulations: list["Simulation"] = Relationship(back_populates="dynamic")
    household_jobs: list["HouseholdJob"] = Relationship(back_populates="dynamic")


class Household(TimestampedModel, table=True):
    __tablename__ = "households"
    __table_args__ = (
        sa.CheckConstraint(
            "year BETWEEN 1900 AND 2200",
            name="ck_households_year",
        ),
    )

    country: str = Field(max_length=16, index=True)
    year: int
    label: str | None = Field(default=None, max_length=255)
    household_data: dict[str, Any] = Field(sa_type=sa.JSON)

    simulations: list["Simulation"] = Relationship(back_populates="household")
    reports: list["Report"] = Relationship(back_populates="household")
    user_associations: list["UserHouseholdAssociation"] = Relationship(
        back_populates="household",
        cascade_delete=True,
    )


class HouseholdJob(IdentifiedModel, table=True):
    __tablename__ = "household_jobs"
    __table_args__ = (
        sa.Index("ix_household_jobs_status_created_at", "status", "created_at"),
    )

    country: str = Field(max_length=16)
    request_data: dict[str, Any] = Field(sa_type=sa.JSON)
    policy_id: UUID | None = Field(
        default=None,
        foreign_key="policies.id",
        ondelete="SET NULL",
    )
    dynamic_id: UUID | None = Field(
        default=None,
        foreign_key="dynamics.id",
        ondelete="SET NULL",
    )
    status: HouseholdJobStatus = Field(
        default=HouseholdJobStatus.PENDING,
        sa_type=enum_type(HouseholdJobStatus, "v2_household_job_status"),
    )
    error_message: str | None = None
    result: dict[str, Any] | None = Field(default=None, sa_type=sa.JSON)
    started_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )

    policy: Policy | None = Relationship(back_populates="household_jobs")
    dynamic: Dynamic | None = Relationship(back_populates="household_jobs")


class Simulation(TimestampedModel, table=True):
    __tablename__ = "simulations"
    __table_args__ = (
        sa.CheckConstraint(
            "(simulation_type = 'household' AND household_id IS NOT NULL "
            "AND dataset_id IS NULL) OR "
            "(simulation_type = 'economy' AND dataset_id IS NOT NULL "
            "AND household_id IS NULL)",
            name="ck_simulations_type_input",
        ),
        sa.CheckConstraint(
            "(filter_field IS NULL) = (filter_value IS NULL)",
            name="ck_simulations_filter_pair",
        ),
        sa.CheckConstraint(
            "year IS NULL OR year BETWEEN 1900 AND 2200",
            name="ck_simulations_year",
        ),
        sa.Index("ix_simulations_status_created_at", "status", "created_at"),
    )

    simulation_type: SimulationType = Field(
        default=SimulationType.ECONOMY,
        sa_type=enum_type(SimulationType, "v2_simulation_type"),
    )
    dataset_id: UUID | None = Field(
        default=None,
        foreign_key="datasets.id",
        ondelete="RESTRICT",
    )
    household_id: UUID | None = Field(
        default=None,
        foreign_key="households.id",
        ondelete="RESTRICT",
    )
    policy_id: UUID | None = Field(
        default=None,
        foreign_key="policies.id",
        ondelete="SET NULL",
    )
    dynamic_id: UUID | None = Field(
        default=None,
        foreign_key="dynamics.id",
        ondelete="SET NULL",
    )
    tax_benefit_model_version_id: UUID = Field(
        foreign_key="tax_benefit_model_versions.id",
        ondelete="RESTRICT",
        index=True,
    )
    output_dataset_id: UUID | None = Field(
        default=None,
        foreign_key="datasets.id",
        ondelete="SET NULL",
    )
    region_id: UUID | None = Field(
        default=None,
        foreign_key="regions.id",
        ondelete="SET NULL",
    )
    status: SimulationStatus = Field(
        default=SimulationStatus.PENDING,
        sa_type=enum_type(SimulationStatus, "v2_simulation_status"),
    )
    error_message: str | None = None
    filter_field: str | None = Field(default=None, max_length=128)
    filter_value: str | None = Field(default=None, max_length=255)
    filter_strategy: str | None = Field(default=None, max_length=64)
    year: int | None = None
    started_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )
    household_result: dict[str, Any] | None = Field(default=None, sa_type=sa.JSON)

    dataset: Dataset | None = Relationship(
        back_populates="input_simulations",
        sa_relationship_kwargs={"foreign_keys": "Simulation.dataset_id"},
    )
    output_dataset: Dataset | None = Relationship(
        back_populates="output_simulations",
        sa_relationship_kwargs={"foreign_keys": "Simulation.output_dataset_id"},
    )
    household: Household | None = Relationship(back_populates="simulations")
    policy: Policy | None = Relationship(back_populates="simulations")
    dynamic: Dynamic | None = Relationship(back_populates="simulations")
    tax_benefit_model_version: TaxBenefitModelVersion = Relationship(
        back_populates="simulations"
    )
    region: Region | None = Relationship(back_populates="simulations")
    baseline_reports: list["Report"] = Relationship(
        back_populates="baseline_simulation",
        sa_relationship_kwargs={"foreign_keys": "Report.baseline_simulation_id"},
    )
    reform_reports: list["Report"] = Relationship(
        back_populates="reform_simulation",
        sa_relationship_kwargs={"foreign_keys": "Report.reform_simulation_id"},
    )
    user_associations: list["UserSimulationAssociation"] = Relationship(
        back_populates="simulation",
        cascade_delete=True,
    )


class UserHouseholdAssociation(TimestampedModel, table=True):
    __tablename__ = "user_household_associations"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id",
            "household_id",
            name="uq_user_household_associations_user_household",
        ),
    )

    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
    )
    household_id: UUID = Field(
        foreign_key="households.id",
        ondelete="CASCADE",
        index=True,
    )
    country: str = Field(max_length=16)
    label: str | None = Field(default=None, max_length=255)

    user: User = Relationship(back_populates="household_associations")
    household: Household = Relationship(back_populates="user_associations")


class UserPolicy(TimestampedModel, table=True):
    __tablename__ = "user_policies"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id",
            "policy_id",
            name="uq_user_policies_user_policy",
        ),
    )

    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
    )
    policy_id: UUID = Field(
        foreign_key="policies.id",
        ondelete="CASCADE",
        index=True,
    )
    country: str = Field(max_length=16)
    label: str | None = Field(default=None, max_length=255)

    user: User = Relationship(back_populates="policy_associations")
    policy: Policy = Relationship(back_populates="user_associations")


class UserSimulationAssociation(TimestampedModel, table=True):
    __tablename__ = "user_simulation_associations"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id",
            "simulation_id",
            name="uq_user_simulation_associations_user_simulation",
        ),
    )

    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
    )
    simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="CASCADE",
        index=True,
    )
    country: str = Field(max_length=16)
    label: str | None = Field(default=None, max_length=255)

    user: User = Relationship(back_populates="simulation_associations")
    simulation: Simulation = Relationship(back_populates="user_associations")


class UserReportAssociation(TimestampedModel, table=True):
    __tablename__ = "user_report_associations"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id",
            "report_id",
            name="uq_user_report_associations_user_report",
        ),
    )

    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
    )
    report_id: UUID = Field(
        foreign_key="reports.id",
        ondelete="CASCADE",
        index=True,
    )
    country: str = Field(max_length=16)
    label: str | None = Field(default=None, max_length=255)
    last_run_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )

    user: User = Relationship(back_populates="report_associations")
    report: "Report" = Relationship(back_populates="user_associations")
