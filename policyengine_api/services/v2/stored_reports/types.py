"""Framework-independent data exchanged by the v2 report layers.

A report compares a baseline and a reform simulation; each calculation of it
is a report run. A budget-window report compares the same policies in each
year of a window of consecutive years: each calculation of it is a
budget-window run, and each year of that a report run naming the window run,
its year and that year's own simulation runs. A household report's
simulations each calculate one stored household, and its result is each
simulation run's calculated household. The simulation service creates
reports and their runs, and its Modal workers store each run's result in the
result tables; the Public API reads all of them directly.
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
    from policyengine_api.services.v2.stored_reports.household_results.types import (
        HouseholdReportFailure,
        HouseholdReportResult,
    )

# A report's status is its newest run's, or not_run while it has none, as a
# report migrated from v1 has none.
ReportStatusName = Literal["not_run", "pending", "running", "succeeded", "failed"]
# What a report compares: two economy simulations, two household simulations,
# or two economy simulations in each year of a budget window.
ReportKind = Literal["economy", "household", "budget_window"]
# The kinds whose runs are their report runs; a budget window's are its
# budget-window runs.
ReportRunsKind = Literal["economy", "household"]
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
    label: str | None
    description: str | None
    year: int | None
    baseline_simulation: ReportSimulationRead | None
    reform_simulation: ReportSimulationRead | None
    options: dict[str, JsonValue]
    created_at: datetime
    current_versions: PackageVersions


@dataclass(frozen=True)
class ReportSummaryRead(ReportDefinitionRead):
    """An economy report's definition, its newest run and the current versions.

    ``region_code`` and ``dataset_name`` are the region and dataset both
    simulations use, null when the report names none.
    """

    kind: Literal["economy"]
    region_code: str | None
    dataset_name: str | None
    status: ReportStatusName
    run: ReportRunRead | None


@dataclass(frozen=True)
class ReportRead(ReportSummaryRead):
    """A report with its newest run's result, once that run has succeeded."""

    result: EconomyResult | None


@dataclass(frozen=True)
class HouseholdReportSummaryRead(ReportDefinitionRead):
    """A household report's definition, its newest run and the current versions.

    Both simulations calculate the stored household ``household_id`` in its
    default year, ``year``; ``reform_simulation`` is None for a report of the
    baseline alone. It has no region or dataset. ``run`` is the newest report
    run, whatever its status and versions, naming each simulation's run.
    """

    kind: Literal["household"]
    household_id: UUID
    status: ReportStatusName
    run: ReportRunRead | None


@dataclass(frozen=True)
class HouseholdReportRead(HouseholdReportSummaryRead):
    """A household report with its newest run's outcome.

    ``result`` holds the calculated households once that run has succeeded;
    ``failure`` says why each side failed once it has failed. Both are None
    otherwise.
    """

    result: HouseholdReportResult | None
    failure: HouseholdReportFailure | None


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

    The window is ``budget_window_size`` years from ``year``, in the region
    ``region_code`` and dataset ``dataset_name``, null when the report names
    none. The report's two simulations are its first year's; each year's
    report run names that year's own simulation runs. ``run`` is the newest
    budget-window run, whatever its status and versions, with its years.
    """

    kind: Literal["budget_window"]
    region_code: str | None
    dataset_name: str | None
    budget_window_size: int
    status: ReportStatusName
    run: BudgetWindowRunRead | None


@dataclass(frozen=True)
class BudgetWindowReportRead(BudgetWindowReportSummaryRead):
    """A budget-window report with its newest run's result, once that run succeeded."""

    result: window_result_types.BudgetWindowResult | None


# A report of any kind these routes read.
StoredReportRead = ReportRead | HouseholdReportRead | BudgetWindowReportRead
StoredReportSummaryRead = (
    ReportSummaryRead | HouseholdReportSummaryRead | BudgetWindowReportSummaryRead
)


@dataclass(frozen=True)
class ReportRunsRead:
    """An economy or household report's runs, newest first, and the current versions.

    ``kind`` is the report's. Each run names the country package and
    PolicyEngine.py versions it ran on; one on other versions than
    ``current_versions``, those the Public API runs, is out of date.
    """

    report_id: UUID
    kind: ReportRunsKind
    runs: tuple[ReportRunRead, ...]
    current_versions: PackageVersions


@dataclass(frozen=True)
class BudgetWindowRunsRead:
    """A budget window's runs, newest first, each with its years.

    Each budget-window run names the versions its years ran on; one on other
    versions than ``current_versions`` is out of date.
    """

    report_id: UUID
    kind: Literal["budget_window"]
    runs: tuple[BudgetWindowRunRead, ...]
    current_versions: PackageVersions


# A report's runs: its report runs, or a budget window's budget-window runs.
StoredReportRunsRead = ReportRunsRead | BudgetWindowRunsRead


@dataclass(frozen=True)
class StoredReportRows:
    """A report's row, the run a read answers and the rows it names.

    ``region_code`` and ``dataset_name`` are those of the report's region and
    dataset, and null when it names none; a simulation is None once deleted.
    ``run`` is a report run that is not a year of a budget window, and
    ``budget_window_run`` a budget-window run, with ``budget_window_years``
    its years' report runs in year order, or None. Read without naming a
    run, each is the report's default: its newest succeeded run that wasn't
    forced (for a window, not recalculated), else its newest such run of any
    status, or None; the service may put the requesting user's newest
    recorded run, or a run the caller names, in its place.
    ``saved_report_name`` and ``saved_report_description`` are the requesting
    user's saved report's, the report's label and description, or None.
    """

    report: Report
    region_code: str | None
    dataset_name: str | None
    baseline_simulation: Simulation | None
    reform_simulation: Simulation | None
    run: ReportRun | None
    budget_window_run: BudgetWindowRun | None
    budget_window_years: tuple[ReportRun, ...]
    saved_report_name: str | None = None
    saved_report_description: str | None = None
