"""Canonical SQLModel tables for stable reports, runs, and run outputs."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import (
    IdentifiedModel,
    TimestampedModel,
    enum_type,
)
from policyengine_api.data.v2.models.simulations import Simulation


class ReportRunStatus(StrEnum):
    """Lifecycle state of a report run; finished runs record a completion time."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ReportRunTrigger(StrEnum):
    """Why a report run started: the report's first run, a manual or a system rerun."""

    INITIAL = "initial"
    MANUAL = "manual"
    SYSTEM = "system"


class OutputStatus(StrEnum):
    """Lifecycle state of one computed output row of a report run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AggregateType(StrEnum):
    """How an aggregate combines a variable's values."""

    SUM = "sum"
    MEAN = "mean"
    COUNT = "count"


class DecileType(StrEnum):
    """Whether deciles rank by income or by wealth."""

    INCOME = "income"
    WEALTH = "wealth"


class Report(TimestampedModel, table=True):
    """Stable report definition; execution state belongs to ReportRun."""

    __tablename__ = "reports"
    __table_args__ = (
        sa.CheckConstraint(
            "year IS NULL OR year BETWEEN 1900 AND 2200",
            name="ck_reports_year",
        ),
        sa.Index("ix_reports_country_type_created_at", "country", "type", "created_at"),
    )

    label: str = Field(max_length=255)
    description: str | None = None
    country: str = Field(max_length=16)
    type: str | None = Field(default=None, max_length=128)
    user_id: UUID | None = Field(
        default=None,
        foreign_key="users.id",
        ondelete="SET NULL",
    )
    tax_benefit_model_id: UUID = Field(
        foreign_key="tax_benefit_models.id",
        ondelete="RESTRICT",
        index=True,
    )
    policy_id: UUID | None = Field(
        default=None,
        foreign_key="policies.id",
        ondelete="SET NULL",
    )
    baseline_simulation_id: UUID | None = Field(
        default=None,
        foreign_key="simulations.id",
        ondelete="SET NULL",
    )
    reform_simulation_id: UUID | None = Field(
        default=None,
        foreign_key="simulations.id",
        ondelete="SET NULL",
    )
    household_id: UUID | None = Field(
        default=None,
        foreign_key="households.id",
        ondelete="RESTRICT",
    )
    dataset_id: UUID | None = Field(
        default=None,
        foreign_key="datasets.id",
        ondelete="SET NULL",
    )
    region_id: UUID | None = Field(
        default=None,
        foreign_key="regions.id",
        ondelete="SET NULL",
    )
    year: int | None = None
    inputs: dict[str, Any] = Field(default_factory=dict, sa_type=sa.JSON)

    baseline_simulation: Simulation | None = Relationship(
        back_populates="baseline_reports",
        sa_relationship_kwargs={"foreign_keys": "Report.baseline_simulation_id"},
    )
    reform_simulation: Simulation | None = Relationship(
        back_populates="reform_reports",
        sa_relationship_kwargs={"foreign_keys": "Report.reform_simulation_id"},
    )
    runs: list["ReportRun"] = Relationship(
        back_populates="report",
        cascade_delete=True,
    )


class ReportRun(TimestampedModel, table=True):
    """One immutable-version execution attempt for a stable report."""

    __tablename__ = "report_runs"
    __table_args__ = (
        sa.UniqueConstraint(
            "report_id",
            "idempotency_key",
            name="uq_report_runs_report_idempotency_key",
        ),
        sa.CheckConstraint(
            "status NOT IN ('succeeded', 'failed') OR completed_at IS NOT NULL",
            name="ck_report_runs_terminal_completion",
        ),
        sa.Index(
            "ix_report_runs_current_output",
            "report_id",
            "status",
            "country_package_version",
            "policyengine_version",
            "completed_at",
            "id",
        ),
    )

    report_id: UUID = Field(
        foreign_key="reports.id",
        ondelete="CASCADE",
    )
    country_package_version: str = Field(max_length=128)
    policyengine_version: str = Field(max_length=128)
    status: ReportRunStatus = Field(
        default=ReportRunStatus.PENDING,
        sa_type=enum_type(ReportRunStatus, "v2_report_run_status"),
    )
    trigger: ReportRunTrigger = Field(
        default=ReportRunTrigger.INITIAL,
        sa_type=enum_type(ReportRunTrigger, "v2_report_run_trigger"),
    )
    idempotency_key: UUID | None = Field(default=None)
    started_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )
    error_message: str | None = None
    markdown: str | None = Field(default=None, sa_type=sa.Text)

    report: Report = Relationship(back_populates="runs")
    aggregates: list["AggregateOutput"] = Relationship(
        back_populates="report_run",
        cascade_delete=True,
    )
    change_aggregates: list["ChangeAggregate"] = Relationship(
        back_populates="report_run",
        cascade_delete=True,
    )
    budget_summaries: list["BudgetSummary"] = Relationship(
        back_populates="report_run",
        cascade_delete=True,
    )
    congressional_district_impacts: list["CongressionalDistrictImpact"] = Relationship(
        back_populates="report_run", cascade_delete=True
    )
    constituency_impacts: list["ConstituencyImpact"] = Relationship(
        back_populates="report_run",
        cascade_delete=True,
    )
    decile_impacts: list["DecileImpact"] = Relationship(
        back_populates="report_run",
        cascade_delete=True,
    )
    inequalities: list["Inequality"] = Relationship(
        back_populates="report_run",
        cascade_delete=True,
    )
    intra_decile_impacts: list["IntraDecileImpact"] = Relationship(
        back_populates="report_run",
        cascade_delete=True,
    )
    local_authority_impacts: list["LocalAuthorityImpact"] = Relationship(
        back_populates="report_run",
        cascade_delete=True,
    )
    poverty_results: list["Poverty"] = Relationship(
        back_populates="report_run",
        cascade_delete=True,
    )
    program_statistics: list["ProgramStatistics"] = Relationship(
        back_populates="report_run",
        cascade_delete=True,
    )


class AggregateOutput(IdentifiedModel, table=True):
    """A sum, mean or count of one variable in one simulation of a report run.

    ``filter_config`` optionally restricts which entities are included.
    """

    __tablename__ = "aggregates"
    __table_args__ = (
        sa.Index("ix_aggregates_report_run_status", "report_run_id", "status"),
    )

    report_run_id: UUID = Field(
        foreign_key="report_runs.id",
        ondelete="CASCADE",
    )
    simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="RESTRICT",
    )
    variable: str = Field(max_length=512)
    aggregate_type: AggregateType = Field(
        sa_type=enum_type(AggregateType, "v2_aggregate_type")
    )
    entity: str | None = Field(default=None, max_length=128)
    filter_config: dict[str, Any] = Field(default_factory=dict, sa_type=sa.JSON)
    status: OutputStatus = Field(
        default=OutputStatus.PENDING,
        sa_type=enum_type(OutputStatus, "v2_output_status"),
    )
    error_message: str | None = None
    result: float | None = None

    report_run: ReportRun = Relationship(back_populates="aggregates")


class ChangeAggregate(IdentifiedModel, table=True):
    """An aggregate of a variable's change from baseline to reform in a report run.

    ``change_geq`` and ``change_leq`` optionally restrict it to entities whose
    change falls within those bounds.
    """

    __tablename__ = "change_aggregates"
    __table_args__ = (
        sa.Index(
            "ix_change_aggregates_report_run_status",
            "report_run_id",
            "status",
        ),
    )

    report_run_id: UUID = Field(
        foreign_key="report_runs.id",
        ondelete="CASCADE",
    )
    baseline_simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="RESTRICT",
    )
    reform_simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="RESTRICT",
    )
    variable: str = Field(max_length=512)
    aggregate_type: AggregateType = Field(
        sa_type=enum_type(AggregateType, "v2_aggregate_type"),
    )
    entity: str | None = Field(default=None, max_length=128)
    filter_config: dict[str, Any] = Field(default_factory=dict, sa_type=sa.JSON)
    change_geq: float | None = None
    change_leq: float | None = None
    status: OutputStatus = Field(
        default=OutputStatus.PENDING,
        sa_type=enum_type(OutputStatus, "v2_output_status"),
    )
    error_message: str | None = None
    result: float | None = None

    report_run: ReportRun = Relationship(back_populates="change_aggregates")


class BudgetSummary(IdentifiedModel, table=True):
    """Baseline and reform totals of one budget variable for a report run.

    One row per run, variable and entity.
    """

    __tablename__ = "budget_summary"
    __table_args__ = (
        sa.UniqueConstraint(
            "report_run_id",
            "variable_name",
            "entity",
            name="uq_budget_summary_run_variable_entity",
        ),
    )

    report_run_id: UUID = Field(
        foreign_key="report_runs.id",
        ondelete="CASCADE",
    )
    baseline_simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="RESTRICT",
    )
    reform_simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="RESTRICT",
    )
    variable_name: str = Field(max_length=512)
    entity: str = Field(max_length=128)
    baseline_total: float | None = None
    reform_total: float | None = None
    change: float | None = None

    report_run: ReportRun = Relationship(back_populates="budget_summaries")


class DecileImpact(IdentifiedModel, table=True):
    """Mean income change and better/worse-off counts in one income quantile.

    ``decile`` runs from 1 to ``quantiles``; there is one row per run, income
    variable, entity, quantile count and decile.
    """

    __tablename__ = "decile_impacts"
    __table_args__ = (
        sa.UniqueConstraint(
            "report_run_id",
            "income_variable",
            "entity",
            "decile",
            "quantiles",
            name="uq_decile_impacts_run_measure",
        ),
        sa.CheckConstraint("quantiles > 0", name="ck_decile_impacts_quantiles"),
        sa.CheckConstraint(
            "decile BETWEEN 1 AND quantiles",
            name="ck_decile_impacts_decile",
        ),
    )

    report_run_id: UUID = Field(
        foreign_key="report_runs.id",
        ondelete="CASCADE",
    )
    baseline_simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="RESTRICT",
    )
    reform_simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="RESTRICT",
    )
    income_variable: str = Field(max_length=512)
    entity: str = Field(max_length=128)
    decile: int
    quantiles: int = 10
    baseline_mean: float | None = None
    reform_mean: float | None = None
    absolute_change: float | None = None
    relative_change: float | None = None
    count_better_off: float | None = None
    count_worse_off: float | None = None
    count_no_change: float | None = None

    report_run: ReportRun = Relationship(back_populates="decile_impacts")


class IntraDecileImpact(IdentifiedModel, table=True):
    """Shares of one decile whose income rises or falls by more or less than 5%.

    One row per run, decile type and decile, where ``decile`` is 0 to 10.
    """

    __tablename__ = "intra_decile_impacts"
    __table_args__ = (
        sa.UniqueConstraint(
            "report_run_id",
            "decile_type",
            "decile",
            name="uq_intra_decile_impacts_run_type_decile",
        ),
        sa.CheckConstraint(
            "decile BETWEEN 0 AND 10",
            name="ck_intra_decile_impacts_decile",
        ),
    )

    report_run_id: UUID = Field(
        foreign_key="report_runs.id",
        ondelete="CASCADE",
    )
    baseline_simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="RESTRICT",
    )
    reform_simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="RESTRICT",
    )
    decile_type: DecileType = Field(
        default=DecileType.INCOME,
        sa_type=enum_type(DecileType, "v2_decile_type"),
    )
    decile: int
    lose_more_than_5pct: float | None = None
    lose_less_than_5pct: float | None = None
    no_change: float | None = None
    gain_less_than_5pct: float | None = None
    gain_more_than_5pct: float | None = None

    report_run: ReportRun = Relationship(back_populates="intra_decile_impacts")


class Inequality(IdentifiedModel, table=True):
    """Gini and top/bottom income shares for one simulation of a report run."""

    __tablename__ = "inequality"
    __table_args__ = (
        sa.UniqueConstraint(
            "report_run_id",
            "simulation_id",
            "income_variable",
            "entity",
            name="uq_inequality_run_simulation_measure",
        ),
    )

    report_run_id: UUID = Field(
        foreign_key="report_runs.id",
        ondelete="CASCADE",
    )
    simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="RESTRICT",
    )
    income_variable: str = Field(max_length=512)
    entity: str = Field(default="household", max_length=128)
    gini: float | None = None
    top_10_share: float | None = None
    top_1_share: float | None = None
    bottom_50_share: float | None = None

    report_run: ReportRun = Relationship(back_populates="inequalities")


class Poverty(IdentifiedModel, table=True):
    """Poverty headcount and rate of one type for one simulation of a report run."""

    __tablename__ = "poverty"
    __table_args__ = (
        sa.Index(
            "ix_poverty_run_simulation_type",
            "report_run_id",
            "simulation_id",
            "poverty_type",
        ),
    )

    report_run_id: UUID = Field(
        foreign_key="report_runs.id",
        ondelete="CASCADE",
    )
    simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="RESTRICT",
    )
    poverty_type: str = Field(max_length=128)
    entity: str = Field(default="person", max_length=128)
    filter_variable: str | None = Field(default=None, max_length=512)
    headcount: float | None = None
    total_population: float | None = None
    rate: float | None = None

    report_run: ReportRun = Relationship(back_populates="poverty_results")


class ProgramStatistics(IdentifiedModel, table=True):
    """Baseline and reform totals, counts, winners and losers for one program.

    One row per run, program and entity; ``is_tax`` marks taxes.
    """

    __tablename__ = "program_statistics"
    __table_args__ = (
        sa.UniqueConstraint(
            "report_run_id",
            "program_name",
            "entity",
            name="uq_program_statistics_run_program_entity",
        ),
    )

    report_run_id: UUID = Field(
        foreign_key="report_runs.id",
        ondelete="CASCADE",
    )
    baseline_simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="RESTRICT",
    )
    reform_simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="RESTRICT",
    )
    program_name: str = Field(max_length=512)
    entity: str = Field(max_length=128)
    is_tax: bool = False
    baseline_total: float | None = None
    reform_total: float | None = None
    change: float | None = None
    baseline_count: float | None = None
    reform_count: float | None = None
    winners: float | None = None
    losers: float | None = None

    report_run: ReportRun = Relationship(back_populates="program_statistics")


class GeographicImpactBase(IdentifiedModel):
    """Shared non-table fields for geographic report-run impacts."""

    report_run_id: UUID = Field(
        foreign_key="report_runs.id",
        ondelete="CASCADE",
    )
    baseline_simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="RESTRICT",
    )
    reform_simulation_id: UUID = Field(
        foreign_key="simulations.id",
        ondelete="RESTRICT",
    )
    average_household_income_change: float
    relative_household_income_change: float
    population: float


class CongressionalDistrictImpact(GeographicImpactBase, table=True):
    """Household income change and population in one US congressional district.

    One row per run and district GEOID.
    """

    __tablename__ = "congressional_district_impacts"
    __table_args__ = (
        sa.UniqueConstraint(
            "report_run_id",
            "district_geoid",
            name="uq_congressional_district_impacts_run_geoid",
        ),
    )

    district_geoid: int
    state_fips: int
    district_number: int

    report_run: ReportRun = Relationship(
        back_populates="congressional_district_impacts"
    )


class ConstituencyImpact(GeographicImpactBase, table=True):
    """Household income change in one UK constituency, with its map coordinates.

    One row per run and constituency code.
    """

    __tablename__ = "constituency_impacts"
    __table_args__ = (
        sa.UniqueConstraint(
            "report_run_id",
            "constituency_code",
            name="uq_constituency_impacts_run_code",
        ),
    )

    constituency_code: str = Field(max_length=64)
    constituency_name: str = Field(max_length=255)
    x: int
    y: int

    report_run: ReportRun = Relationship(back_populates="constituency_impacts")


class LocalAuthorityImpact(GeographicImpactBase, table=True):
    """Household income change in one UK local authority, with its map coordinates.

    One row per run and local authority code.
    """

    __tablename__ = "local_authority_impacts"
    __table_args__ = (
        sa.UniqueConstraint(
            "report_run_id",
            "local_authority_code",
            name="uq_local_authority_impacts_run_code",
        ),
    )

    local_authority_code: str = Field(max_length=64)
    local_authority_name: str = Field(max_length=255)
    x: int
    y: int

    report_run: ReportRun = Relationship(back_populates="local_authority_impacts")
