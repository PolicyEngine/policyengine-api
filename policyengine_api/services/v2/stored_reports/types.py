"""Framework-independent data exchanged by the v2 report layers.

A report compares a baseline and a reform simulation; each calculation of it
is a report run. A budget-window report compares the same policies in each
year of a window of consecutive years: each calculation of it is a
budget-window run, and each year of that a report run naming the window run,
its year and that year's own simulation runs. The
simulation service creates reports and their runs, and its Modal workers
store each run's result in the result tables; the Public API reads all of
them directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from pydantic import JsonValue

    from policyengine_api.data.v2.models import (
        BudgetWindowRun,
        Report,
        ReportRun,
        Simulation,
    )
    from policyengine_api.services.v2.simulation_service.types import (
        PackageVersions,
    )
    from policyengine_api.services.v2.stored_reports.budget_window_results import (
        types as window_result_types,
    )
    from policyengine_api.services.v2.stored_reports.economy_results.types import (
        EconomyResult,
    )

# A report's status is its newest run's, or not_run while it has none, as a
# report migrated from v1 has none.
ReportStatusName = Literal["not_run", "pending", "running", "succeeded", "failed"]
# What a report compares: two economy simulations, two household simulations,
# or two economy simulations in each year of a budget window.
ReportKind = Literal["economy", "household", "budget_window"]
ReportRunTriggerName = Literal["initial", "manual", "system"]


@dataclass(frozen=True)
class ReportRunRead:
    """One calculation of a report, and the package versions it ran on.

    ``trigger`` is ``initial`` for the run the report's creation started.
    ``error_message`` says why a failed run failed.
    """

    id: UUID
    status: Literal["pending", "running", "succeeded", "failed"]
    trigger: ReportRunTriggerName
    country_package_version: str
    policyengine_version: str
    baseline_simulation_run_id: UUID
    reform_simulation_run_id: UUID | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class ReportSimulationRead:
    """A simulation a report compares: its policy and dynamic, null for current law."""

    id: UUID
    policy_id: UUID | None
    dynamic_id: UUID | None


@dataclass(frozen=True)
class ReportDefinitionRead:
    """What every report's read gives: its definition and the current versions.

    ``current_versions`` are the country package and PolicyEngine.py versions
    the Public API serves now; a newest run on other versions is out of date.
    ``options`` are the options the report was created with, as stored.
    """

    id: UUID
    country_id: str
    label: str
    description: str | None
    year: int | None
    region_code: str | None
    dataset_name: str | None
    baseline_simulation: ReportSimulationRead | None
    reform_simulation: ReportSimulationRead | None
    options: dict[str, JsonValue]
    created_at: datetime
    current_versions: PackageVersions


@dataclass(frozen=True)
class ReportSummaryRead(ReportDefinitionRead):
    """An economy report's definition, its newest run and the current versions."""

    kind: Literal["economy"]
    status: ReportStatusName
    run: ReportRunRead | None


@dataclass(frozen=True)
class ReportRead(ReportSummaryRead):
    """A report with its newest run's result, once that run has succeeded."""

    result: EconomyResult | None


@dataclass(frozen=True)
class BudgetWindowYearRead(ReportRunRead):
    """One year of a budget-window run: the report run calculating that year."""

    year: int


@dataclass(frozen=True)
class BudgetWindowRunRead:
    """One calculation of a budget-window report, and its years in year order.

    ``status`` is ``pending`` until a year starts running, ``running`` while
    its years run, ``failed`` once a year has failed, and ``succeeded`` once
    every year has; ``error_message``
    says why a failed run failed. ``recalculate`` says whether its years
    calculate their simulations again rather than reusing successful runs.
    ``country_package_version`` and ``policyengine_version`` are the versions
    its years run on, which the simulation service creates together on one
    version; they are null for a run with no year.
    """

    id: UUID
    status: Literal["pending", "running", "succeeded", "failed"]
    trigger: ReportRunTriggerName
    recalculate: bool
    country_package_version: str | None
    policyengine_version: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    years: tuple[BudgetWindowYearRead, ...]


@dataclass(frozen=True)
class BudgetWindowReportSummaryRead(ReportDefinitionRead):
    """A budget-window report's definition, its newest run and the current versions.

    The window is ``budget_window_size`` years from ``year``. The report's
    two simulations are its first year's; each year's report run names that
    year's own simulation runs. ``run`` is the newest budget-window run,
    whatever its status and versions, with its years.
    """

    kind: Literal["budget_window"]
    budget_window_size: int
    status: ReportStatusName
    run: BudgetWindowRunRead | None


@dataclass(frozen=True)
class BudgetWindowReportRead(BudgetWindowReportSummaryRead):
    """A budget-window report with its newest run's result, once that run succeeded."""

    result: window_result_types.BudgetWindowResult | None


# A report of either kind these routes read.
StoredReportRead = ReportRead | BudgetWindowReportRead
StoredReportSummaryRead = ReportSummaryRead | BudgetWindowReportSummaryRead


@dataclass(frozen=True)
class ReportRunsRead:
    """A report's runs, newest first, and the versions the Public API runs.

    Each run names the country package and PolicyEngine.py versions it ran
    on; one on other versions than ``current_versions`` is out of date.
    """

    report_id: UUID
    kind: Literal["economy"]
    runs: tuple[ReportRunRead, ...]
    current_versions: PackageVersions


@dataclass(frozen=True)
class StoredReportRows:
    """A report's row, its newest runs and the catalog and simulation rows it names.

    ``region_code`` and ``dataset_name`` are those of the report's region and
    dataset, and null when it names none; a simulation is None once deleted.
    ``newest_run`` is the report run created last that is not a year of a
    budget window, whatever its status and versions, or None.
    ``newest_budget_window_run`` is the budget-window run created last, or
    None, and ``budget_window_years`` its years' report runs in year order.
    """

    report: Report
    region_code: str | None
    dataset_name: str | None
    baseline_simulation: Simulation | None
    reform_simulation: Simulation | None
    newest_run: ReportRun | None
    newest_budget_window_run: BudgetWindowRun | None
    budget_window_years: tuple[ReportRun, ...]
