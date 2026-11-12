"""Framework-independent data exchanged by the v2 report layers.

A report compares a baseline and a reform simulation; each calculation of it
is a report run. The simulation service creates reports and their runs, and
its Modal workers store each run's result in the result tables; the Public
API reads all of them directly. A household report's simulations each
calculate one stored household, and its result is each simulation run's
calculated household.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from pydantic import JsonValue

    from policyengine_api.data.v2.models import Report, ReportRun, Simulation
    from policyengine_api.services.v2.simulation_service.types import (
        PackageVersions,
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
class HouseholdReportSummaryRead(ReportDefinitionRead):
    """A household report's definition, its newest run and the current versions.

    Both simulations calculate the stored household ``household_id`` in
    ``year``; ``reform_simulation`` is None for a report of the baseline
    alone. It has no region or dataset. ``run`` is the newest report run,
    whatever its status and versions, naming each simulation's run.
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


# A report of any kind these routes read.
StoredReportRead = ReportRead | HouseholdReportRead
StoredReportSummaryRead = ReportSummaryRead | HouseholdReportSummaryRead


@dataclass(frozen=True)
class StoredReportRows:
    """A report's row, its newest run and the catalog and simulation rows it names.

    ``region_code`` and ``dataset_name`` are those of the report's region and
    dataset, and null when it names none; a simulation is None once deleted.
    ``newest_run`` is the report run created last, whatever its status and
    versions, or None.
    """

    report: Report
    region_code: str | None
    dataset_name: str | None
    baseline_simulation: Simulation | None
    reform_simulation: Simulation | None
    newest_run: ReportRun | None
