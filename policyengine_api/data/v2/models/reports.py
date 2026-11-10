"""Canonical SQLModel tables for stable reports and their runs.

A report run compares one baseline simulation run with one reform simulation
run; a budget-window report has a run per year of each calculation. Their
results are in ``run_results``.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlmodel import Field, Relationship

from policyengine_api.data.v2.models.base import (
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
from policyengine_api.data.v2.models.simulations import Simulation
from policyengine_api.data.v2.models.users import User

if TYPE_CHECKING:
    from policyengine_api.data.v2.models.run_results import (
        AggregateOutput,
        BudgetSummary,
        ChangeAggregate,
        CongressionalDistrictImpact,
        ConstituencyImpact,
        DecileImpact,
        IntraDecileImpact,
        LaborSupplyDecileResponse,
        LaborSupplyResponse,
        LocalAuthorityImpact,
        ProgramStatistics,
    )

# A budget window compares at most this many years, none after LAST_YEAR.
MAX_BUDGET_WINDOW_YEARS = 75
LAST_YEAR = 2200


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
        sa.CheckConstraint(
            "budget_window_size IS NULL OR (household_id IS NULL "
            f"AND budget_window_size BETWEEN 1 AND {MAX_BUDGET_WINDOW_YEARS} "
            f"AND year IS NOT NULL AND year + budget_window_size - 1 <= {LAST_YEAR})",
            name="ck_reports_budget_window_size",
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
    budget_window_size: int | None = None
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
    budget_window_runs: list["BudgetWindowRun"] = Relationship(
        back_populates="report",
        cascade_delete=True,
    )


class BudgetWindowRun(TimestampedModel, table=True):
    """One calculation of a budget-window report on one catalog version.

    Each year of the window is a report run of the same report that names this
    row and its year. ``recalculate`` says whether those years calculate their
    simulations again instead of reusing successful runs. The simulation
    service creates the window's year runs and starts the first five; each
    year's Modal coordinator starts the next unstarted year when its own year
    finishes, and the last year to finish marks this row succeeded. A failed
    year fails it.
    """

    __tablename__ = "budget_window_runs"
    __table_args__ = (
        sa.UniqueConstraint("id", "report_id", name="uq_budget_window_runs_id_report"),
        sa.CheckConstraint(
            "status NOT IN ('succeeded', 'failed') OR completed_at IS NOT NULL",
            name="ck_budget_window_runs_terminal_completion",
        ),
        sa.Index(
            "ix_budget_window_runs_report_id_created_at", "report_id", "created_at"
        ),
    )

    report_id: UUID = Field(
        foreign_key="reports.id",
        ondelete="CASCADE",
    )
    tax_benefit_model_version_id: UUID = Field(
        foreign_key="tax_benefit_model_versions.id",
        ondelete="RESTRICT",
        index=True,
    )
    trigger: ReportRunTrigger = Field(
        default=ReportRunTrigger.INITIAL,
        sa_type=enum_type(ReportRunTrigger, "v2_report_run_trigger"),
    )
    recalculate: bool = False
    status: ReportRunStatus = Field(
        default=ReportRunStatus.PENDING,
        sa_type=enum_type(ReportRunStatus, "v2_report_run_status"),
    )
    error_message: str | None = None
    started_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
    )

    report: Report = Relationship(back_populates="budget_window_runs")


class ReportRun(TimestampedModel, table=True):
    """One immutable-version execution attempt for a stable report.

    It compares ``baseline_simulation_run_id`` with
    ``reform_simulation_run_id``; a household report with only a baseline has
    no reform run. A year of a budget window names its ``budget_window_run_id``
    and ``year``, at most one report run per year of a window run. An economy
    comparison's cliff impact is the baseline's and reform's cliff gap and
    share, stored together or not at all; ``spm_provenance`` is the SPM receipt
    and ``data_version`` the data release it used. Its labour supply response
    has its own two tables.
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
            "year IS NULL OR year BETWEEN 1900 AND 2200",
            name="ck_report_runs_year",
        ),
        sa.CheckConstraint(
            "budget_window_run_id IS NULL OR year IS NOT NULL",
            name="ck_report_runs_budget_window_year",
        ),
        sa.UniqueConstraint(
            "budget_window_run_id",
            "year",
            name="uq_report_runs_budget_window_run_id_year",
        ),
        # A year's report run belongs to a budget-window run of its own report,
        # which owns it as the report owns its runs.
        sa.ForeignKeyConstraint(
            ["budget_window_run_id", "report_id"],
            ["budget_window_runs.id", "budget_window_runs.report_id"],
            name="fk_report_runs_budget_window_run_id_budget_window_runs",
            ondelete="CASCADE",
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
    budget_window_run_id: UUID | None = None
    year: int | None = None
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
