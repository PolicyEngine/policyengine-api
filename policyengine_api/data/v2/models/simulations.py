"""Canonical SQLModel tables for v2 simulations and their runs."""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import TimestampedModel, enum_type

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.reports import (
        Inequality,
        Poverty,
        Report,
        ReportRunSimulationRun,
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
    Its dataset, household, policy, dynamic, catalog version and region are
    logical references to the Public API's rows, without foreign keys: the
    simulation service checks them before it writes the simulation.
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
    dataset_id: UUID | None = None
    household_id: UUID | None = None
    policy_id: UUID | None = None
    dynamic_id: UUID | None = None
    tax_benefit_model_version_id: UUID = Field(index=True)
    region_id: UUID | None = None
    filter_field: str | None = Field(default=None, max_length=128)
    filter_value: str | None = Field(default=None, max_length=255)
    filter_strategy: str | None = Field(default=None, max_length=64)
    year: int | None = None

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
    """One run of a simulation on one catalog version and .py version.

    ``tax_benefit_model_version_id``, ``dataset_id`` and ``region_id`` name the
    catalog version, dataset and region the run used, which a run on a newer
    version resolves again. They are logical references: the catalog belongs to
    the Public API, and the simulation service checks them before it writes the
    run. A household simulation's run stores its household in
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
        sa.Index(
            "ix_simulation_runs_current_output",
            "simulation_id",
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
    tax_benefit_model_version_id: UUID
    country_package_version: str = Field(max_length=128)
    policyengine_version: str = Field(max_length=128)
    dataset_id: UUID | None = None
    region_id: UUID | None = None
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
    report_run_memberships: list["ReportRunSimulationRun"] = Relationship(
        back_populates="simulation_run"
    )
    poverty_results: list["Poverty"] = Relationship(
        back_populates="simulation_run",
        cascade_delete=True,
    )
    inequalities: list["Inequality"] = Relationship(
        back_populates="simulation_run",
        cascade_delete=True,
    )
