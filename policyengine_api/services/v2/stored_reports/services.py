"""Create reports through the simulation service, and read them.

Reading a report reads it within its country (``reports.country``), with its
newest run: the run created last, whatever its status and versions. That
differs from ``policyengine_api.data.v2.report_runs.select_current_report_run``,
which picks the newest succeeded run on the versions the Public API runs: a
report whose newest run used an older PolicyEngine.py version still answers
that run's result, beside the versions the Public API runs now, so the caller
can show the stored result and say a newer model version exists. Nothing is
calculated again on a read. A report with no run, as a report migrated from
v1 has none, answers its definition with no result.

The result is rebuilt from the newest run's result rows once it has
succeeded. A budget-window report's newest run is its newest budget-window
run, read with its years; once that run has succeeded, its result is the
budget-window format, rebuilt from each year's budget rows. Reading a
window's definition and runs never reads those rows, so only a read of a
succeeded window can find them unreadable. A household report's result is
instead each of its simulation runs' calculated household
(``simulation_runs.household_result``), read once its newest report run has
succeeded, and each side's failure once it has failed. Lists name at most 25
reports and read them, with their newest runs and any window's years, in two
queries, without results.

Creating a report or budget window checks the country and the policies it
names (and a household report's household), asks the simulation service to
create and start it, then reads it back from the tables. Once the simulation
service has answered with the report's ID, the report exists: a failure to
read it back raises CreatedReportUnreadableError, which names it, so the
caller reads it rather than submitting it again.
Re-runs and run lists are not here.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.data.v2.models import ReportRunStatus
from policyengine_api.services.v2.simulation_service.types import (
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.stored_reports.budget_window_results import (
    transformations as window_result_transformations,
)
from policyengine_api.services.v2.stored_reports.database_connectors import (
    reads_budget_window_results as window_result_reads,
)
from policyengine_api.services.v2.stored_reports.database_connectors import (
    reads_household_results as household_result_reads,
)
from policyengine_api.services.v2.stored_reports.database_connectors import (
    reads_results as result_reads,
)
from policyengine_api.services.v2.stored_reports.database_connectors.reads import (
    read_report_rows,
)
from policyengine_api.services.v2.stored_reports.economy_results import (
    transformations as result_transformations,
)
from policyengine_api.services.v2.stored_reports.household_results import (
    transformations as household_result_transformations,
)
from policyengine_api.services.v2.stored_reports.household_results.validators import (
    require_household_report_result,
)
from policyengine_api.services.v2.stored_reports.transformations import (
    budget_window_read,
    budget_window_summary_read,
    household_report_read,
    household_report_summary_read,
    listed_reports,
    report_kind,
    report_read,
    report_summary_read,
)
from policyengine_api.services.v2.stored_reports.validators import (
    CreatedReportUnreadableError,
    ReportStorageError,
    require_readable_report,
    require_reform_run,
    require_report,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.services.v2.simulation_service.types import (
        PackageVersions,
        ReportCreationInput,
        SimulationServiceClient,
    )
    from policyengine_api.services.v2.stored_reports.database_session import (
        StoredReportDatabaseSession,
    )
    from policyengine_api.services.v2.stored_reports.types import (
        BudgetWindowReportRead,
        HouseholdReportRead,
        StoredReportRead,
        StoredReportRows,
        StoredReportSummaryRead,
    )


class SubmissionsNotConfiguredError(SimulationServiceUnavailableError):
    """The service was built without a way to submit to the simulation service."""


@contextmanager
def _storage_failures() -> Iterator[None]:
    """Raise ReportStorageError for a failed database read."""
    try:
        yield
    except SQLAlchemyError as error:
        msg = "V2 report storage is unavailable"
        raise ReportStorageError(msg) from error


def _summary_read(
    stored: StoredReportRows, *, current_versions: PackageVersions
) -> StoredReportSummaryRead:
    """Return the report's definition and newest run, as its kind reads them."""
    kind = report_kind(stored.report)
    if kind == "household":
        return household_report_summary_read(stored, current_versions=current_versions)
    if kind == "budget_window":
        return budget_window_summary_read(stored, current_versions=current_versions)
    return report_summary_read(stored, current_versions=current_versions)


class V2StoredReportService:
    """Read v2 reports and their results, and create reports of every kind."""

    def __init__(
        self,
        database_session: StoredReportDatabaseSession,
        *,
        current_versions: Callable[[str], PackageVersions],
        submissions: SimulationServiceClient | None = None,
    ) -> None:
        """Read through ``database_session``; create through ``submissions``.

        ``current_versions`` returns the country package and PolicyEngine.py
        versions the Public API runs for a country. ``submissions`` is the
        checking ``SimulationSubmissionService``; without it, creating a
        report raises SubmissionsNotConfiguredError.
        """
        self._database_session = database_session
        self._current_versions = current_versions
        self._submissions = submissions

    def get_report(self, *, country_id: str, report_id: UUID) -> StoredReportRead:
        """Return the country's report, its newest run and that run's result.

        The report is an economy report, a household report or a budget
        window. Raise StoredReportNotFoundError when the country has no such
        report, EconomyResultUnreadableError when a succeeded run's rows lack
        a part every result has, HouseholdResultUnreadableError when a
        succeeded household report run's calculated households cannot be
        read, BudgetWindowResultUnreadableError when a succeeded window run's
        years cannot give its result, and ReportStorageError when the
        database cannot be read.
        """
        with _storage_failures(), self._database_session.read() as session:
            stored = require_report(
                next(
                    iter(
                        read_report_rows(
                            session, country_id=country_id, report_ids=(report_id,)
                        )
                    ),
                    None,
                ),
                report_id=report_id,
                country_id=country_id,
            )
            kind = require_readable_report(stored)
            if kind == "budget_window":
                return self._budget_window(session, stored)
            if kind == "household":
                return self._household_report(session, stored)
            run = stored.newest_run
            result = None
            if run is not None and run.status is ReportRunStatus.SUCCEEDED:
                result = result_transformations.economy_result(
                    result_reads.read_economy_result_rows(
                        session,
                        country_id=country_id,
                        report_run=run,
                        reform_simulation_run_id=require_reform_run(run),
                    )
                )
            return report_read(
                stored,
                current_versions=self._current_versions(country_id),
                result=result,
            )

    def _budget_window(
        self, session: Session, stored: StoredReportRows
    ) -> BudgetWindowReportRead:
        """Return a budget window, with its result once its newest run succeeded."""
        window_run = stored.newest_budget_window_run
        result = None
        if window_run is not None and window_run.status is ReportRunStatus.SUCCEEDED:
            result = window_result_transformations.budget_window_result(
                window_result_reads.read_budget_window_result_rows(
                    session,
                    report=stored.report,
                    year_runs=stored.budget_window_years,
                )
            )
        return budget_window_read(
            stored,
            current_versions=self._current_versions(stored.report.country),
            result=result,
        )

    def _household_report(
        self, session: Session, stored: StoredReportRows
    ) -> HouseholdReportRead:
        """Return a household report with its newest run's outcome.

        Its calculated households are read once that run has succeeded, and
        each side's failure once it has failed.
        """
        run = stored.newest_run
        result = failure = None
        if run is not None and run.status in {
            ReportRunStatus.SUCCEEDED,
            ReportRunStatus.FAILED,
        }:
            rows = household_result_reads.read_household_result_rows(
                session, report_run=run
            )
            if run.status is ReportRunStatus.SUCCEEDED:
                result = require_household_report_result(run, rows)
            else:
                failure = household_result_transformations.household_report_failure(
                    run, rows
                )
        return household_report_read(
            stored,
            current_versions=self._current_versions(stored.report.country),
            result=result,
            failure=failure,
        )

    def list_reports(
        self, *, country_id: str, report_ids: Sequence[UUID]
    ) -> tuple[StoredReportSummaryRead, ...]:
        """Return the country's reports among ``report_ids``, without results.

        They are in the order named, each once; unknown reports and other
        countries' are left out. Raise ReportStorageError when the database
        cannot be read.
        """
        with _storage_failures(), self._database_session.read() as session:
            rows = read_report_rows(
                session, country_id=country_id, report_ids=report_ids
            )
            current_versions = self._current_versions(country_id)
            return tuple(
                _summary_read(stored, current_versions=current_versions)
                for stored in listed_reports(rows, report_ids=report_ids)
            )

    def create_report(self, report_input: ReportCreationInput) -> StoredReportRead:
        """Create the report through the simulation service and return it as stored.

        Each kind of report goes through its own submission. Raise the
        submission's errors (see ``SimulationSubmissionService``), and
        CreatedReportUnreadableError, caused by the read's own error, when the
        report the simulation service created cannot be read back in the
        country: not stored there, the database unavailable, or any other
        failure of the read.
        """
        if self._submissions is None:
            msg = "The simulation service is not configured here"
            raise SubmissionsNotConfiguredError(msg)
        if report_input.kind == "budget_window":
            report_id = self._submissions.submit_budget_window(report_input).report_id
        elif report_input.kind == "household":
            report_id = self._submissions.submit_household_report(
                report_input
            ).report_id
        else:
            report_id = self._submissions.submit_report(report_input).report_id
        try:
            return self.get_report(
                country_id=report_input.country_id, report_id=report_id
            )
        except Exception as error:
            # The report exists whatever failed, so the caller gets its ID.
            raise CreatedReportUnreadableError(
                report_id=report_id, country_id=report_input.country_id
            ) from error
