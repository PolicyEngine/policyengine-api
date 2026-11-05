"""Canonical SQLModel tables for stable reports, runs, and run outputs.

A report run compares one baseline simulation run with one reform simulation
run. Results that compare them belong to the report run and name the two
simulation runs; each such row is unique within its report run. Poverty and
inequality, which describe one simulation, belong to a simulation run.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import (
    IdentifiedModel,
    TimestampedModel,
    enum_type,
)
from policyengine_api.data.v2.models.households import Household
from policyengine_api.data.v2.models.metadata import (
    Dataset,
    Region,
    TaxBenefitModel,
)
from policyengine_api.data.v2.models.policies import Policy
from policyengine_api.data.v2.models.simulations import Simulation, SimulationRun
from policyengine_api.data.v2.models.users import User


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
    """Stable report definition; execution state belongs to ReportRun.

    The simulation service writes reports, and the Public API the user, model,
    policy, household, dataset and region a report names; each service writes
    only its own tables, and the foreign keys between them stay. Deleting the
    user, policy, dataset or region clears the reference, which for the user
    is found through ``user_id``'s index; the model and household can't be
    deleted while a report names them.
    """

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
        index=True,
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

    user: User | None = Relationship(back_populates="reports")
    tax_benefit_model: TaxBenefitModel = Relationship(back_populates="reports")
    policy: Policy | None = Relationship(back_populates="reports")
    baseline_simulation: Simulation | None = Relationship(
        back_populates="baseline_reports",
        sa_relationship_kwargs={"foreign_keys": "Report.baseline_simulation_id"},
    )
    reform_simulation: Simulation | None = Relationship(
        back_populates="reform_reports",
        sa_relationship_kwargs={"foreign_keys": "Report.reform_simulation_id"},
    )
    household: Household | None = Relationship(back_populates="reports")
    dataset: Dataset | None = Relationship(back_populates="reports")
    region: Region | None = Relationship(back_populates="reports")
    runs: list["ReportRun"] = Relationship(
        back_populates="report",
        cascade_delete=True,
    )


class ReportRun(TimestampedModel, table=True):
    """One immutable-version execution attempt for a stable report.

    It compares ``baseline_simulation_run_id`` with
    ``reform_simulation_run_id``; a household report with only a baseline has
    no reform run. An economy comparison's cliff impact is the baseline's and
    reform's cliff gap and share, stored together or not at all;
    ``spm_provenance`` is the SPM receipt and ``data_version`` the data release
    it used. Its labour supply response has its own two tables.
    """

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
        sa.CheckConstraint(
            "(baseline_cliff_gap IS NULL) = (baseline_cliff_share IS NULL) "
            "AND (baseline_cliff_gap IS NULL) = (reform_cliff_gap IS NULL) "
            "AND (baseline_cliff_gap IS NULL) = (reform_cliff_share IS NULL)",
            name="ck_report_runs_cliff_impact_complete",
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
        sa.Index("ix_report_runs_status_started_at", "status", "started_at"),
    )

    report_id: UUID = Field(
        foreign_key="reports.id",
        ondelete="CASCADE",
    )
    baseline_simulation_run_id: UUID = Field(
        foreign_key="simulation_runs.id",
        ondelete="RESTRICT",
        index=True,
    )
    reform_simulation_run_id: UUID | None = Field(
        default=None,
        foreign_key="simulation_runs.id",
        ondelete="RESTRICT",
        index=True,
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
    modal_call_id: str | None = Field(default=None, max_length=255)
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
    baseline_cliff_gap: float | None = None
    baseline_cliff_share: float | None = None
    reform_cliff_gap: float | None = None
    reform_cliff_share: float | None = None
    spm_provenance: dict[str, Any] | None = Field(
        default=None,
        sa_type=sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
    )
    data_version: str | None = Field(default=None, max_length=128)

    report: Report = Relationship(back_populates="runs")
    labor_supply_responses: list["LaborSupplyResponse"] = Relationship(
        back_populates="report_run",
        cascade_delete=True,
    )
    labor_supply_decile_responses: list["LaborSupplyDecileResponse"] = Relationship(
        back_populates="report_run",
        cascade_delete=True,
    )
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
    intra_decile_impacts: list["IntraDecileImpact"] = Relationship(
        back_populates="report_run",
        cascade_delete=True,
    )
    local_authority_impacts: list["LocalAuthorityImpact"] = Relationship(
        back_populates="report_run",
        cascade_delete=True,
    )
    program_statistics: list["ProgramStatistics"] = Relationship(
        back_populates="report_run",
        cascade_delete=True,
    )


class LaborSupplyResponse(IdentifiedModel, table=True):
    """The labour supply response to the reform in one report run.

    One row per report run. The earnings changes come from the income and
    substitution effects (.py's ``income_lsr`` and ``substitution_lsr``) and
    total ``total_earnings_change``; ``relative_income_effect`` and
    ``relative_substitution_effect`` are relative to baseline earnings. The
    weekly hours are the total hours worked under the baseline and the reform,
    and their change split into the two effects.
    """

    __tablename__ = "labor_supply_responses"
    __table_args__ = (
        sa.UniqueConstraint("report_run_id", name="uq_labor_supply_responses_run"),
    )

    report_run_id: UUID = Field(
        foreign_key="report_runs.id",
        ondelete="CASCADE",
    )
    income_effect_earnings_change: float
    substitution_effect_earnings_change: float
    total_earnings_change: float
    revenue_change: float
    relative_income_effect: float
    relative_substitution_effect: float
    baseline_weekly_hours: float
    reform_weekly_hours: float
    weekly_hours_change: float
    weekly_hours_income_effect: float
    weekly_hours_substitution_effect: float

    report_run: ReportRun = Relationship(back_populates="labor_supply_responses")


class LaborSupplyDecileResponse(IdentifiedModel, table=True):
    """The labour supply response in one income decile of one report run.

    One row per report run and decile, as .py numbers them. The average effects
    are per household; the relative effects are relative to the decile's
    baseline earnings, which .py reports only for deciles above zero, so they
    may be null.
    """

    __tablename__ = "labor_supply_decile_responses"
    __table_args__ = (
        sa.UniqueConstraint(
            "report_run_id",
            "decile",
            name="uq_labor_supply_decile_responses_run_decile",
        ),
    )

    report_run_id: UUID = Field(
        foreign_key="report_runs.id",
        ondelete="CASCADE",
    )
    decile: int
    average_income_effect: float | None = None
    average_substitution_effect: float | None = None
    relative_income_effect: float | None = None
    relative_substitution_effect: float | None = None

    report_run: ReportRun = Relationship(back_populates="labor_supply_decile_responses")


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

    One row per report run, variable and entity.
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
    baseline_simulation_run_id: UUID = Field(
        foreign_key="simulation_runs.id",
        ondelete="RESTRICT",
    )
    reform_simulation_run_id: UUID = Field(
        foreign_key="simulation_runs.id",
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

    ``decile`` runs from 1 to ``quantiles``; there is one row per report run,
    income variable, decile variable, entity, quantile count and decile.
    ``decile_variable`` names a variable that groups the households instead of
    the income variable's own deciles, such as ``household_wealth_decile``; rows
    without one count as equal.
    """

    __tablename__ = "decile_impacts"
    __table_args__ = (
        sa.UniqueConstraint(
            "report_run_id",
            "income_variable",
            "decile_variable",
            "entity",
            "decile",
            "quantiles",
            name="uq_decile_impacts_run_measure",
            postgresql_nulls_not_distinct=True,
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
    baseline_simulation_run_id: UUID = Field(
        foreign_key="simulation_runs.id",
        ondelete="RESTRICT",
    )
    reform_simulation_run_id: UUID = Field(
        foreign_key="simulation_runs.id",
        ondelete="RESTRICT",
    )
    income_variable: str = Field(max_length=512)
    decile_variable: str | None = Field(default=None, max_length=512)
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

    One row per report run, decile type and decile, where ``decile`` is 0 to
    10.
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
    baseline_simulation_run_id: UUID = Field(
        foreign_key="simulation_runs.id",
        ondelete="RESTRICT",
    )
    reform_simulation_run_id: UUID = Field(
        foreign_key="simulation_runs.id",
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
    """Gini and top/bottom income shares for one simulation run."""

    __tablename__ = "inequality"
    __table_args__ = (
        sa.UniqueConstraint(
            "simulation_run_id",
            "income_variable",
            "entity",
            name="uq_inequality_simulation_run_measure",
        ),
    )

    simulation_run_id: UUID = Field(
        foreign_key="simulation_runs.id",
        ondelete="CASCADE",
    )
    income_variable: str = Field(max_length=512)
    entity: str = Field(default="household", max_length=128)
    gini: float | None = None
    top_10_share: float | None = None
    top_1_share: float | None = None
    bottom_50_share: float | None = None

    simulation_run: SimulationRun = Relationship(back_populates="inequalities")


class Poverty(IdentifiedModel, table=True):
    """Poverty headcount and rate of one type for one simulation run.

    One row per run, poverty type, entity, filter variable and filter group:
    ``filter_variable`` selects people (``age``) and ``filter_group`` names the
    group (``child``). Missing values count as equal, so each run has one
    unfiltered row per type and entity.
    """

    __tablename__ = "poverty"
    __table_args__ = (
        sa.UniqueConstraint(
            "simulation_run_id",
            "poverty_type",
            "entity",
            "filter_variable",
            "filter_group",
            name="uq_poverty_simulation_run_measure",
            postgresql_nulls_not_distinct=True,
        ),
    )

    simulation_run_id: UUID = Field(
        foreign_key="simulation_runs.id",
        ondelete="CASCADE",
    )
    poverty_type: str = Field(max_length=128)
    entity: str = Field(default="person", max_length=128)
    filter_variable: str | None = Field(default=None, max_length=512)
    filter_group: str | None = Field(default=None, max_length=64)
    headcount: float | None = None
    total_population: float | None = None
    rate: float | None = None

    simulation_run: SimulationRun = Relationship(back_populates="poverty_results")


class ProgramStatistics(IdentifiedModel, table=True):
    """Baseline and reform totals, counts, winners and losers for one program.

    One row per report run, program and entity; ``is_tax`` marks taxes. The
    economy output's detailed budget names neither the entity nor whether a
    program is a tax, so both may be null, and rows without an entity count as
    equal.
    """

    __tablename__ = "program_statistics"
    __table_args__ = (
        sa.UniqueConstraint(
            "report_run_id",
            "program_name",
            "entity",
            name="uq_program_statistics_run_program_entity",
            postgresql_nulls_not_distinct=True,
        ),
    )

    report_run_id: UUID = Field(
        foreign_key="report_runs.id",
        ondelete="CASCADE",
    )
    baseline_simulation_run_id: UUID = Field(
        foreign_key="simulation_runs.id",
        ondelete="RESTRICT",
    )
    reform_simulation_run_id: UUID = Field(
        foreign_key="simulation_runs.id",
        ondelete="RESTRICT",
    )
    program_name: str = Field(max_length=512)
    entity: str | None = Field(default=None, max_length=128)
    is_tax: bool | None = None
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
    baseline_simulation_run_id: UUID = Field(
        foreign_key="simulation_runs.id",
        ondelete="RESTRICT",
    )
    reform_simulation_run_id: UUID = Field(
        foreign_key="simulation_runs.id",
        ondelete="RESTRICT",
    )
    average_household_income_change: float
    relative_household_income_change: float
    population: float


class UKAreaImpactBase(GeographicImpactBase):
    """Shared non-table disclosure fields of a UK area's impact.

    ``disclosure_tier`` is ``reported``, or ``approximate`` when the area's
    sample is thin; the ``_lower`` and ``_upper`` fields bound each income
    change's 90% interval. All are null for results without disclosure control.
    """

    disclosure_tier: str | None = Field(default=None, max_length=16)
    average_household_income_change_lower: float | None = None
    average_household_income_change_upper: float | None = None
    relative_household_income_change_lower: float | None = None
    relative_household_income_change_upper: float | None = None


def _disclosure_tier_check(table_name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        "disclosure_tier IS NULL OR disclosure_tier IN ('reported', 'approximate')",
        name=f"ck_{table_name}_disclosure_tier",
    )


class CongressionalDistrictImpact(GeographicImpactBase, table=True):
    """Household income change and population in one US congressional district.

    One row per report run and district GEOID, with the shares of people who
    gain, lose or see no change.
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
    winner_percentage: float
    loser_percentage: float
    no_change_percentage: float

    report_run: ReportRun = Relationship(
        back_populates="congressional_district_impacts"
    )


class ConstituencyImpact(UKAreaImpactBase, table=True):
    """Household income change in one UK constituency.

    One row per report run and constituency code.
    """

    __tablename__ = "constituency_impacts"
    __table_args__ = (
        sa.UniqueConstraint(
            "report_run_id",
            "constituency_code",
            name="uq_constituency_impacts_run_code",
        ),
        _disclosure_tier_check("constituency_impacts"),
    )

    constituency_code: str = Field(max_length=64)
    constituency_name: str = Field(max_length=255)

    report_run: ReportRun = Relationship(back_populates="constituency_impacts")


class LocalAuthorityImpact(UKAreaImpactBase, table=True):
    """Household income change in one UK local authority.

    One row per report run and local authority code.
    """

    __tablename__ = "local_authority_impacts"
    __table_args__ = (
        sa.UniqueConstraint(
            "report_run_id",
            "local_authority_code",
            name="uq_local_authority_impacts_run_code",
        ),
        _disclosure_tier_check("local_authority_impacts"),
    )

    local_authority_code: str = Field(max_length=64)
    local_authority_name: str = Field(max_length=255)

    report_run: ReportRun = Relationship(back_populates="local_authority_impacts")
