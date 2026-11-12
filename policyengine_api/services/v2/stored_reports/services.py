"""Create economy reports through the simulation service, and read them.

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
succeeded. Lists name at most 25 reports and read them, with their newest
runs, in one query, without results.

Creating a report checks the country and the policies the report names, asks
the simulation service to create and start it, then reads it back from the
tables. Once the simulation service has answered with the report's ID, the
report exists: a failure to read it back raises CreatedReportUnreadableError,
which names it, so the caller reads it rather than submitting it again.
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
from policyengine_api.services.v2.stored_reports.database_connectors import (
    reads_results as result_reads,
)
from policyengine_api.services.v2.stored_reports.database_connectors.reads import (
    read_report_rows,
)
from policyengine_api.services.v2.stored_reports.economy_results import (
    transformations as result_transformations,
)
from policyengine_api.services.v2.stored_reports.transformations import (
    listed_economy_reports,
    report_read,
    report_summary_read,
)
from policyengine_api.services.v2.stored_reports.validators import (
    CreatedReportUnreadableError,
    ReportStorageError,
    require_economy_report,
    require_reform_run,
    require_report,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from uuid import UUID

    from policyengine_api.services.v2.simulation_service.types import (
        EconomyReportCreationInput,
        PackageVersions,
        SimulationServiceClient,
    )
    from policyengine_api.services.v2.stored_reports.database_session import (
        StoredReportDatabaseSession,
    )
    from policyengine_api.services.v2.stored_reports.types import (
        ReportRead,
        ReportSummaryRead,
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


class V2StoredReportService:
    """Read v2 reports and their results, and create economy reports."""

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

    def get_report(self, *, country_id: str, report_id: UUID) -> ReportRead:
        """Return the country's economy report, its newest run and that run's result.

        Raise StoredReportNotFoundError when the country has no such report,
        ReportKindUnsupportedError for a household report or budget window,
        EconomyResultUnreadableError when a succeeded run's rows lack a part
        every result has, and ReportStorageError when the database cannot be
        read.
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
            require_economy_report(stored)
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

    def list_reports(
        self, *, country_id: str, report_ids: Sequence[UUID]
    ) -> tuple[ReportSummaryRead, ...]:
        """Return the country's economy reports among ``report_ids``, without results.

        They are in the order named, each once; unknown reports, other
        countries' and reports of other kinds are left out. Raise
        ReportStorageError when the database cannot be read.
        """
        with _storage_failures(), self._database_session.read() as session:
            rows = read_report_rows(
                session, country_id=country_id, report_ids=report_ids
            )
            current_versions = self._current_versions(country_id)
            return tuple(
                report_summary_read(stored, current_versions=current_versions)
                for stored in listed_economy_reports(rows, report_ids=report_ids)
            )

    def create_report(self, report_input: EconomyReportCreationInput) -> ReportRead:
        """Create the report through the simulation service and return it as stored.

        Raise the submission's errors (see ``SimulationSubmissionService``),
        and CreatedReportUnreadableError, caused by the read's own error, when
        the report the simulation service created cannot be read back in the
        country: not stored there, the database unavailable, or any other
        failure of the read.
        """
        if self._submissions is None:
            msg = "The simulation service is not configured here"
            raise SubmissionsNotConfiguredError(msg)
        submitted = self._submissions.submit_report(report_input)
        try:
            return self.get_report(
                country_id=report_input.country_id, report_id=submitted.report_id
            )
        except Exception as error:
            # The report exists whatever failed, so the caller gets its ID.
            raise CreatedReportUnreadableError(
                report_id=submitted.report_id, country_id=report_input.country_id
            ) from error
