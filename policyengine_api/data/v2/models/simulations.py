"""Canonical SQLModel tables for v2 simulations and their runs."""

from datetime import datetime
from enum import StrEnum
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
    from policyengine_api.data.v2.models.reports import (
        Inequality,
        Poverty,
        Report,
    )


class SimulationStatus(StrEnum):
    """Lifecycle state of one run of a v2 simulation."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SimulationType(StrEnum):
    """Whether a simulation runs on one household or on a population dataset."""

    HOUSEHOLD = "household"
    ECONOMY = "economy"


class Simulation(TimestampedModel, table=True):
    """A simulation of exactly one household or one dataset, matching its type.

    It defines what to calculate; each calculation of it is a ``SimulationRun``.
    The simulation service writes it, and the Public API the rows it names;
    each service writes only its own tables, and the foreign keys between them
    stay. Deleting its policy, dynamic or region clears that reference; its
    household, input dataset and catalog version cannot be deleted while it
    exists.
    """

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
    region_id: UUID | None = Field(
        default=None,
        foreign_key="regions.id",
        ondelete="SET NULL",
    )
    filter_field: str | None = Field(default=None, max_length=128)
    filter_value: str | None = Field(default=None, max_length=255)
    filter_strategy: str | None = Field(default=None, max_length=64)
    year: int | None = None

    dataset: Dataset | None = Relationship(
        back_populates="input_simulations",
        sa_relationship_kwargs={"foreign_keys": "Simulation.dataset_id"},
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
    runs: list["SimulationRun"] = Relationship(
        back_populates="simulation",
        cascade_delete=True,
    )


class SimulationRun(TimestampedModel, table=True):
    """One run of a simulation for one year on one catalog and .py version.

    A simulation has a run per year it is calculated for, so a budget window
    compares a report's same two simulations in every year of the window.

    ``tax_benefit_model_version_id``, ``dataset_id`` and ``region_id`` name the
    catalog version, dataset and region the run used, which a run on a newer
    version resolves again. They are foreign keys to the Public API's catalog
    with the same delete rules as the simulation's: the catalog version and
    dataset can't be deleted while a run names them, and deleting the region
    clears the reference. A household simulation's run stores its household in
    ``household_result``; an economy run's output file is ``output_uri``, with
    its SHA-256. Each poverty and inequality result belongs to one run.
    """

    __tablename__ = "simulation_runs"
    __table_args__ = (
        sa.CheckConstraint(
            "status NOT IN ('succeeded', 'failed') OR completed_at IS NOT NULL",
            name="ck_simulation_runs_terminal_completion",
        ),
        sa.CheckConstraint(
            "(output_uri IS NULL) = (output_sha256 IS NULL)",
            name="ck_simulation_runs_output_pair",
        ),
        sa.CheckConstraint(
            "output_sha256 IS NULL OR length(output_sha256) = 64",
            name="ck_simulation_runs_output_sha256_length",
        ),
        sa.CheckConstraint(
            "year BETWEEN 1900 AND 2200",
            name="ck_simulation_runs_year",
        ),
        sa.Index(
            "ix_simulation_runs_current_output",
            "simulation_id",
            "year",
            "status",
            "country_package_version",
            "policyengine_version",
            "completed_at",
            "id",
        ),
        sa.Index("ix_simulation_runs_status_started_at", "status", "started_at"),
    )

    simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="CASCADE",
    )
    year: int
    tax_benefit_model_version_id: UUID = Field(
        foreign_key="tax_benefit_model_versions.id",
        ondelete="RESTRICT",
        index=True,
    )
    country_package_version: str = Field(max_length=128)
    policyengine_version: str = Field(max_length=128)
    dataset_id: UUID | None = Field(
        default=None,
        foreign_key="datasets.id",
        ondelete="RESTRICT",
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
    modal_call_id: str | None = Field(default=None, max_length=255)
    error_message: str | None = None
    started_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )
    household_result: dict[str, Any] | None = Field(default=None, sa_type=sa.JSON)
    output_uri: str | None = Field(default=None, max_length=2048)
    output_sha256: str | None = Field(default=None, max_length=64)

    simulation: Simulation = Relationship(back_populates="runs")
    poverty_results: list["Poverty"] = Relationship(
        back_populates="simulation_run",
        cascade_delete=True,
    )
    inequalities: list["Inequality"] = Relationship(
        back_populates="simulation_run",
        cascade_delete=True,
    )
