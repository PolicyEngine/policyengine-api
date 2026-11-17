"""Create reports through the simulation service, and read them.

Reading a report reads it within its country (``reports.country``), as the
requesting user sees it. Its run is the one the read names (one of the
report's own report runs, or a budget window's budget-window run), else the
requesting user's newest recorded run of it (``user_report_run_associations``),
else its default run: its newest succeeded run that wasn't forced, else its
newest run that wasn't forced, on whatever versions. A run on an older
PolicyEngine.py version still answers its result, beside the versions the
Public API runs now, so the caller can show the stored result and say a
newer model version exists; the newer run someone else started is offered
from the report's run list, never in its place. Its label and description
are the requesting user's saved report's name and description, and None
for anyone else. Nothing is calculated again on a read. A report with no
run, as a report migrated from v1 has none, answers its definition with no
result.

The result is rebuilt from the run's result rows once it has succeeded; a
local-area report's (a UK-wide or nation report on the dataset its catalog
version gives local areas) also lists its withheld area codes. An economy
report's read also gives its run's cliffs (``ReportCliffsRead``). A
budget-window report's run is a budget-window run, read with its years;
once that run has succeeded, its result is the budget-window format,
rebuilt from each year's budget rows. Reading a
window's definition and runs never reads those rows, so only a read of a
succeeded window can find them unreadable. A household report's result is
instead each of its simulation runs' calculated household
(``simulation_runs.household_result``), read once its report run has
succeeded, and each side's failure once it has failed. Lists name at most 25
reports and read them as a read without a run does, with any window's
years, without results: two queries, and with a user three or four more for
their labels and their newest recorded runs. A search finds the country's
reports that share a ``dataset_independent_key``, which a national report
shares with its local-area report: the 25 created last, newest first, read
as a list reads them.

Creating a report or budget window checks the country and the policies it
names (and a household report's household), asks the simulation service to
create and start it, then reads it back from the tables with the run the
service's answer names: a new run, or, once the service finds runs by key,
an existing one the request joined, which needn't be the newest. Once the
simulation service has answered with the report's ID, the report exists: a
failure to read it back raises CreatedReportUnreadableError, which names it,
so the caller reads it rather than submitting it again.

Running a report again reads it in its country, checks its country and the
policies its simulations name as a new report of its kind is checked, has the
simulation service start its run on the current versions, then reads the
report back with the run the service's answer names: a new run, or one
already pending, running or succeeded on those versions that the request
joined. The database session is closed while the simulation service is
asked. A failure to read it back raises RerunReportUnreadableError, since
the run exists. A report's runs
are listed newest first, whatever their status and versions, beside the
versions the Public API runs, so a caller can tell which are out of date: an
economy or household report's report runs, or a budget window's
budget-window runs with their years.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.data.v2.models import ReportRunStatus, ReportRunTrigger
from policyengine_api.data.v2.models.base import utc_now
from policyengine_api.query_parameters import MAXIMUM_LISTED_REPORTS
from policyengine_api.services.v2.report_run_records.types import ReportRunRequest
from policyengine_api.services.v2.simulation_service.types import (
    ReportRerunInput,
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
    read_budget_window_years,
    read_report_rows,
    search_report_ids,
)
from policyengine_api.services.v2.stored_reports.database_connectors.reads_runs import (
    read_budget_window_run,
    read_budget_window_runs,
    read_report_run,
    read_report_runs,
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
from policyengine_api.services.v2.stored_reports.requester_views.services import (
    requesters_view,
)
from policyengine_api.services.v2.stored_reports.transformations import (
    budget_window_read,
    budget_window_runs_read,
    budget_window_summary_read,
    household_report_read,
    household_report_summary_read,
    listed_reports,
    report_cliffs,
    report_kind,
    report_policy_ids,
    report_read,
    report_runs_read,
    report_summary_read,
)
from policyengine_api.services.v2.stored_reports.validators import (
    CreatedReportUnreadableError,
    ReportRunNotRecordedError,
    ReportRunRecordsNotConfiguredError,
    ReportStorageError,
    RerunReportUnreadableError,
    require_admin_to_force,
    require_cliffs_available,
    require_reform_run,
    require_report,
    require_report_run,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.services.v2.identity.types import AccountPrincipal
    from policyengine_api.services.v2.report_run_records.types import (
        CheckedRequester,
        ReportRunRecorder,
    )
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
        StoredReportRunsRead,
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


def _stored_report(
    session: Session, *, country_id: str, report_id: UUID
) -> StoredReportRows:
    """Return the country's report with its default run (see ``read_report_rows``).

    Raise StoredReportNotFoundError when the country has no such report.
    """
    rows = read_report_rows(session, country_id=country_id, report_ids=(report_id,))
    return require_report(
        next(iter(rows), None), report_id=report_id, country_id=country_id
    )


def _with_run(
    session: Session, stored: StoredReportRows, run_id: UUID
) -> StoredReportRows:
    """Return the report's rows with its run ``run_id`` in place of the one read.

    A budget window's run is a budget-window run, read with its years; any
    other report's is one of its own report runs. Raise ReportRunNotFoundError
    when the report has no such run.
    """
    report_id = stored.report.id
    if report_kind(stored.report) == "budget_window":
        window_run = require_report_run(
            read_budget_window_run(session, report_id=report_id, run_id=run_id),
            report_id=report_id,
            run_id=run_id,
        )
        years = read_budget_window_years(session, [window_run.id])
        return replace(
            stored,
            budget_window_run=window_run,
            budget_window_years=years.get(window_run.id, ()),
        )
    run = require_report_run(
        read_report_run(session, report_id=report_id, run_id=run_id),
        report_id=report_id,
        run_id=run_id,
    )
    return replace(stored, run=run)


@dataclass(frozen=True)
class _RunRecording:
    """The recorder of a request naming its user, and that user as checked."""

    recorder: ReportRunRecorder
    requester: CheckedRequester


def _record_request(recording: _RunRecording, request: ReportRunRequest) -> UUID:
    """Record the requester's request for its run; return the user it names.

    Raise ReportRunNotRecordedError, caused by the record's own error,
    whatever fails: the run exists, so the caller reads it.
    """
    try:
        return recording.recorder.record(recording.requester, request)
    except Exception as error:
        raise ReportRunNotRecordedError(
            report_id=request.report_id,
            run_id=request.run_id,
            country_id=request.country_id,
        ) from error


def _summary_read(
    stored: StoredReportRows, *, current_versions: PackageVersions
) -> StoredReportSummaryRead:
    """Return the report's definition and the run read, as its kind reads them."""
    kind = report_kind(stored.report)
    if kind == "household":
        return household_report_summary_read(stored, current_versions=current_versions)
    if kind == "budget_window":
        return budget_window_summary_read(stored, current_versions=current_versions)
    return report_summary_read(stored, current_versions=current_versions)


class V2StoredReportService:
    """Read v2 reports and results, create reports of every kind, and run them again."""

    def __init__(
        self,
        database_session: StoredReportDatabaseSession,
        *,
        current_versions: Callable[[str], PackageVersions],
        submissions: SimulationServiceClient | None = None,
        run_records: ReportRunRecorder | None = None,
    ) -> None:
        """Read through ``database_session``; create through ``submissions``.

        ``current_versions`` returns the country package and PolicyEngine.py
        versions the Public API runs for a country. ``submissions`` is the
        checking ``SimulationSubmissionService``; without it, creating a
        report or running one again raises SubmissionsNotConfiguredError.
        ``run_records`` records each user's request for a run; without it, a
        create or re-run naming its user raises
        ReportRunRecordsNotConfiguredError.
        """
        self._database_session = database_session
        self._current_versions = current_versions
        self._submissions = submissions
        self._run_records = run_records

    def _run_recording(
        self, requester: AccountPrincipal | None
    ) -> _RunRecording | None:
        """Check a request's user before anything starts; return how to record it.

        Return None for a request naming no user, whose run nobody records.
        Raise ReportRunRecordsNotConfiguredError without a recorder, and the
        recorder's check's errors.
        """
        if requester is None:
            return None
        if self._run_records is None:
            msg = "Users' report runs are not recorded here"
            raise ReportRunRecordsNotConfiguredError(msg)
        return _RunRecording(
            recorder=self._run_records,
            requester=self._run_records.check_requester(requester),
        )

    def _configured_submissions(self) -> SimulationServiceClient:
        """Return the submissions, or raise SubmissionsNotConfiguredError."""
        if self._submissions is None:
            msg = "The simulation service is not configured here"
            raise SubmissionsNotConfiguredError(msg)
        return self._submissions

    def get_report(
        self,
        *,
        country_id: str,
        report_id: UUID,
        run_id: UUID | None = None,
        requester: AccountPrincipal | None = None,
    ) -> StoredReportRead:
        """Return the country's report, a run and that run's result, as a user sees it.

        The run is ``run_id``; without it, the requester's newest recorded
        run of the report, else the report's default run (its newest
        succeeded run that wasn't forced, else its newest run that wasn't
        forced). The label and description are the requester's saved
        report's, or None. The report is an economy report, a household
        report or a budget window. Raise StoredReportNotFoundError when the
        country has no such report, ReportRunNotFoundError when it has no run
        ``run_id`` (a budget window's runs are its budget-window runs; any
        other report's, its own report runs),
        StandardUserRequiresSignInError for an unauthenticated credential
        that names a signed-in user, EconomyResultUnreadableError when a
        succeeded run's rows lack a part every result has,
        HouseholdResultUnreadableError when a
        succeeded household report run's calculated households cannot be
        read, BudgetWindowResultUnreadableError when a succeeded window run's
        years cannot give its result, and ReportStorageError when the
        database cannot be read.
        """
        return self._read_report(
            country_id=country_id,
            report_id=report_id,
            run_id=run_id,
            requester=requester,
        )

    def _read_report(
        self,
        *,
        country_id: str,
        report_id: UUID,
        run_id: UUID | None,
        requester: AccountPrincipal | None,
        recorded_user_id: UUID | None = None,
    ) -> StoredReportRead:
        """Read the report as ``get_report`` does, for a requester or a recorded user.

        ``recorded_user_id`` names the user a request was just recorded for,
        whom a read back is for: after a sign-in converted a browser's user
        in place, the browser's principal names a signed-in user.
        """
        with _storage_failures(), self._database_session.read() as session:
            stored = _stored_report(session, country_id=country_id, report_id=report_id)
            (stored,) = requesters_view(
                session,
                [stored],
                requester=requester,
                recorded_user_id=recorded_user_id,
                with_requested_runs=run_id is None,
            )
            if run_id is not None:
                stored = _with_run(session, stored, run_id)
            kind = report_kind(stored.report)
            if kind == "budget_window":
                return self._budget_window(session, stored)
            if kind == "household":
                return self._household_report(session, stored)
            run = stored.run
            result = cliffs = None
            if run is not None:
                reform_simulation_run_id = require_reform_run(run)
                cliff_calculations = result_reads.read_cliff_calculations(
                    session,
                    baseline_simulation_run_id=run.baseline_simulation_run_id,
                    reform_simulation_run_id=reform_simulation_run_id,
                )
                cliffs = report_cliffs(cliff_calculations)
                if run.status is ReportRunStatus.SUCCEEDED:
                    result = result_transformations.economy_result(
                        result_reads.read_economy_result_rows(
                            session,
                            country_id=country_id,
                            report_run=run,
                            reform_simulation_run_id=reform_simulation_run_id,
                            on_local_area_dataset=stored.on_local_area_dataset,
                            cliff_calculations=cliff_calculations,
                        )
                    )
            return report_read(
                stored,
                current_versions=self._current_versions(country_id),
                result=result,
                cliffs=cliffs,
            )

    def _budget_window(
        self, session: Session, stored: StoredReportRows
    ) -> BudgetWindowReportRead:
        """Return a budget window, with its result once the run read succeeded."""
        window_run = stored.budget_window_run
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
        """Return a household report with the outcome of the run read.

        Its calculated households are read once that run has succeeded, and
        each side's failure once it has failed.
        """
        run = stored.run
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
        self,
        *,
        country_id: str,
        report_ids: Sequence[UUID],
        requester: AccountPrincipal | None = None,
    ) -> tuple[StoredReportSummaryRead, ...]:
        """Return the country's reports among ``report_ids``, without results.

        They are in the order named, each once, as ``get_report`` reads them
        without a run: with the requester's newest recorded run, else the
        report's default run, and the requester's saved report's label.
        Unknown reports and other countries' are left out. Raise
        StandardUserRequiresSignInError for an unauthenticated credential
        that names a signed-in user, and ReportStorageError when the database
        cannot be read.
        """
        with _storage_failures(), self._database_session.read() as session:
            rows = requesters_view(
                session,
                read_report_rows(session, country_id=country_id, report_ids=report_ids),
                requester=requester,
                with_requested_runs=True,
            )
            current_versions = self._current_versions(country_id)
            return tuple(
                _summary_read(stored, current_versions=current_versions)
                for stored in listed_reports(rows, report_ids=report_ids)
            )

    def search_reports(
        self,
        *,
        country_id: str,
        dataset_independent_key: str,
        requester: AccountPrincipal | None = None,
    ) -> tuple[StoredReportSummaryRead, ...]:
        """Return the country's reports that share a dataset-independent key.

        They are read as ``list_reports`` reads them, without results: the
        ``MAXIMUM_LISTED_REPORTS`` reports created last, newest first (ties
        going to the larger ID), of every kind. Raise
        StandardUserRequiresSignInError for an unauthenticated credential
        that names a signed-in user, and ReportStorageError when the database
        cannot be read.
        """
        with _storage_failures(), self._database_session.read() as session:
            report_ids = search_report_ids(
                session,
                country_id=country_id,
                dataset_independent_key=dataset_independent_key,
                limit=MAXIMUM_LISTED_REPORTS,
            )
            rows = requesters_view(
                session,
                read_report_rows(session, country_id=country_id, report_ids=report_ids),
                requester=requester,
                with_requested_runs=True,
            )
            current_versions = self._current_versions(country_id)
            return tuple(
                _summary_read(stored, current_versions=current_versions)
                for stored in listed_reports(rows, report_ids=report_ids)
            )

    def create_report(
        self,
        report_input: ReportCreationInput,
        *,
        requester: AccountPrincipal | None = None,
    ) -> StoredReportRead:
        """Create the report through the simulation service and return it as stored.

        Each kind of report goes through its own submission, and the report
        is read back with the run the simulation service's answer names (a
        budget window's budget-window run). With a ``requester``, it is
        checked before the simulation service is asked, and the request is
        recorded for its user (trigger ``initial``) once the service has
        answered: that run, or each year's report run of a budget window's.
        Raise the
        recorder's check's errors, the submission's errors (see
        ``SimulationSubmissionService``), ReportRunNotRecordedError when the
        request could not be recorded, and CreatedReportUnreadableError,
        caused by the read's own error, when the report the simulation
        service created cannot be read back in the country: not stored there,
        the database unavailable, or any other failure of the read.
        """
        submissions = self._configured_submissions()
        requested_at = utc_now()
        recording = self._run_recording(requester)
        if report_input.kind == "budget_window":
            window = submissions.submit_budget_window(report_input)
            request = ReportRunRequest(
                country_id=report_input.country_id,
                report_id=window.report_id,
                budget_window_run_id=window.budget_window_run_id,
                requested_at=requested_at,
                trigger=ReportRunTrigger.INITIAL,
            )
        else:
            submitted = (
                submissions.submit_household_report(report_input)
                if report_input.kind == "household"
                else submissions.submit_report(report_input)
            )
            request = ReportRunRequest(
                country_id=report_input.country_id,
                report_id=submitted.report_id,
                report_run_id=submitted.report_run_id,
                requested_at=requested_at,
                trigger=ReportRunTrigger.INITIAL,
            )
        report_id = request.report_id
        recorded_user_id = (
            None if recording is None else _record_request(recording, request)
        )
        try:
            return self._read_report(
                country_id=report_input.country_id,
                report_id=report_id,
                run_id=request.run_id,
                requester=None,
                recorded_user_id=recorded_user_id,
            )
        except Exception as error:
            # The report exists whatever failed, so the caller gets its ID.
            raise CreatedReportUnreadableError(
                report_id=report_id,
                run_id=request.run_id,
                country_id=report_input.country_id,
            ) from error

    def rerun_report(
        self,
        *,
        country_id: str,
        report_id: UUID,
        force: bool,
        include_cliffs: bool = False,
        requester: AccountPrincipal | None = None,
    ) -> StoredReportRead:
        """Run the country's report again; return it with the run the request ended on.

        That is the run the simulation service's answer names: a new run, or
        one already pending, running or succeeded on the current versions
        that the request joined (a budget window's budget-window run). Without
        ``force``, each side reuses a run of its own simulation that succeeded
        on the current versions; with it, both are calculated again (a budget
        window's new run then recalculates each year). A household report's
        sides are always calculated again. Only an admin user may force a
        re-run; ``include_cliffs`` asks for an economy report run's cliffs
        too. With a ``requester``, it is
        checked before the simulation service is asked, and the request is
        recorded for its user (trigger ``manual``, forced or not) once the
        service has answered: that run, or each year's report run of a budget
        window's. Raise StoredReportNotFoundError when the country has no such
        report, ForcedRerunRequiresSignInError for a forced re-run naming no
        user, ForcedRerunRequiresAdminError for one by a user below admin and
        CliffsNotAvailableError for a household report's or window's cliffs,
        each before the simulation service is asked, ReportStorageError when
        it cannot be read, the recorder's check's
        errors, the submission's checks' and the simulation service's errors
        (see ``SimulationSubmissionService.rerun_report``),
        ReportRunNotRecordedError when the request could not be recorded, and
        RerunReportUnreadableError, caused by the read's own error, when the
        report cannot be read back once its run was started, or without a
        cause when a budget window's answer names no budget-window run.
        """
        submissions = self._configured_submissions()
        requested_at = utc_now()
        with _storage_failures(), self._database_session.read() as session:
            stored = _stored_report(session, country_id=country_id, report_id=report_id)
        kind = report_kind(stored.report)
        recording = self._run_recording(requester)
        if force:
            require_admin_to_force(None if recording is None else recording.requester)
        require_cliffs_available(kind, include_cliffs=include_cliffs)
        started = submissions.rerun_report(
            ReportRerunInput(
                country_id=country_id,
                report_id=report_id,
                kind=kind,
                force=force,
                policy_ids=report_policy_ids(stored),
                include_cliffs=include_cliffs,
            )
        )
        if kind != "budget_window":
            request = ReportRunRequest(
                country_id=country_id,
                report_id=report_id,
                report_run_id=started.report_run_id,
                requested_at=requested_at,
                trigger=ReportRunTrigger.MANUAL,
            )
        elif started.budget_window_run_id is not None:
            request = ReportRunRequest(
                country_id=country_id,
                report_id=report_id,
                budget_window_run_id=started.budget_window_run_id,
                requested_at=requested_at,
                trigger=ReportRunTrigger.MANUAL,
            )
        else:
            # The run exists, but the answer doesn't say which window run.
            raise RerunReportUnreadableError(
                report_id=report_id, run_id=None, country_id=country_id
            )
        recorded_user_id = (
            None if recording is None else _record_request(recording, request)
        )
        try:
            return self._read_report(
                country_id=country_id,
                report_id=report_id,
                run_id=request.run_id,
                requester=None,
                recorded_user_id=recorded_user_id,
            )
        except Exception as error:
            # The run exists whatever failed, so the caller reads it.
            raise RerunReportUnreadableError(
                report_id=report_id, run_id=request.run_id, country_id=country_id
            ) from error

    def list_report_runs(
        self, *, country_id: str, report_id: UUID
    ) -> StoredReportRunsRead:
        """Return the runs of the country's report, newest first.

        They are an economy or household report's report runs, or a budget
        window's budget-window runs, each with its years. Raise
        StoredReportNotFoundError when the country has no such report, and
        ReportStorageError when the database cannot be read.
        """
        with _storage_failures(), self._database_session.read() as session:
            stored = _stored_report(session, country_id=country_id, report_id=report_id)
            current_versions = self._current_versions(country_id)
            # A kind added to ReportKind later fails mypy (a missing return)
            # until it has a case here.
            match report_kind(stored.report):
                case "budget_window":
                    window_runs = read_budget_window_runs(session, report_id=report_id)
                    return budget_window_runs_read(
                        stored,
                        window_runs,
                        read_budget_window_years(
                            session, [window_run.id for window_run in window_runs]
                        ),
                        current_versions=current_versions,
                    )
                case "economy" | "household" as kind:
                    return report_runs_read(
                        stored,
                        read_report_runs(session, report_id=report_id),
                        kind=kind,
                        current_versions=current_versions,
                    )
