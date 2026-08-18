"""Canonical SQLModel table for v2 simulations."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import TimestampedModel, enum_type
from policyengine_api.data.v2.models.households import Household
from policyengine_api.data.v2.models.metadata import (
    Dataset,
    Region,
    TaxBenefitModelVersion,
)
from policyengine_api.data.v2.models.policies import Dynamic, Policy

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.associations import UserSimulationAssociation
    from policyengine_api.data.v2.models.reports import Report


class SimulationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SimulationType(str, Enum):
    HOUSEHOLD = "household"
    ECONOMY = "economy"


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
