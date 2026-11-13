"""Record each user's requests for v2 report runs.

The report routes record a request once the simulation service has answered
which run it ended on, created or joined: the requesting user's
``user_report_run_associations`` row for that run, written in one
transaction with the user's provisioning (a signed-in identity's user, or a
signed-out browser's unauthenticated user, as any user write provisions
it) and with the ``last_run_at`` of the user's saved reports naming the
report. Before the simulation service is asked, the requester is checked,
so a browser credential that names a signed-in user is refused before
anything is created, and the user it has then is the one the record names:
a browser whose user signing in merged into an account while the simulation
service was asked is not recorded under a new user re-created with its ID,
and one converted in place meanwhile is recorded as the account it became.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.services.v2.identity.database_connectors.reads import (
    read_user,
)
from policyengine_api.services.v2.identity.services import (
    find_principal_user_in_session,
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.report_run_records.database_connectors import (
    creates as record_creates,
)
from policyengine_api.services.v2.report_run_records.database_connectors import (
    reads as record_reads,
)
from policyengine_api.services.v2.report_run_records.database_connectors import (
    updates as record_updates,
)
from policyengine_api.services.v2.report_run_records.types import (
    CheckedRequester,
    ReportRunRecordRead,
)
from policyengine_api.services.v2.report_run_records.validators import (
    ReportRunRecordStorageError,
    require_requester_user,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from policyengine_api.services.v2.identity.types import AccountPrincipal
    from policyengine_api.services.v2.report_run_records.database_session import (
        ReportRunRecordDatabaseSession,
    )
    from policyengine_api.services.v2.report_run_records.types import (
        ReportRunRequest,
    )


@contextmanager
def _storage_failures() -> Iterator[None]:
    """Raise ReportRunRecordStorageError for a failed database read or write."""
    try:
        yield
    except SQLAlchemyError as error:
        msg = "V2 report storage is unavailable"
        raise ReportRunRecordStorageError(msg) from error


class ReportRunRecordService:
    """Record the report runs users ask for."""

    def __init__(self, database_session: ReportRunRecordDatabaseSession) -> None:
        """Read and write through ``database_session``."""
        self._database_session = database_session

    def check_requester(self, principal: AccountPrincipal) -> CheckedRequester:
        """Check a principal before anything starts, and name its user if it has one.

        Nothing is written. Raise StandardUserRequiresSignInError for an
        unauthenticated credential that names a signed-in user, and
        ReportRunRecordStorageError when the database cannot be read.
        """
        with _storage_failures(), self._database_session.read() as session:
            found = find_principal_user_in_session(session, principal)
        if found is None:
            return CheckedRequester(principal=principal, user_id=None)
        return CheckedRequester(
            principal=principal, user_id=found.user_id, user_type=found.user_type
        )

    def record(self, requester: CheckedRequester, request: ReportRunRequest) -> None:
        """Record the request for each run it ended on, in one transaction.

        A budget window's request records each year's report run of its
        budget-window run, read in the same transaction. The record names the
        user the check found, held ``FOR SHARE`` so a
        sign-in merging or converting it waits, and kept as it is when it
        was converted in place meanwhile; with none found, the principal's
        user is provisioned as any user write provisions it. A run the user
        already has a record of keeps it. When this request recorded a run,
        the user's saved reports naming the report take its ``requested_at``
        as their ``last_run_at`` if it is later. Raise RequesterUserGoneError
        when the user the check found no longer exists (merged into an
        account, or its account deleted), StandardUserRequiresSignInError
        when an unauthenticated credential with no user then names a
        signed-in one, and ReportRunRecordStorageError when the database
        cannot be written.
        """
        with _storage_failures(), self._database_session.transaction() as session:
            if requester.user_id is not None:
                user_id = require_requester_user(
                    requester.user_id,
                    exists=read_user(session, requester.user_id, for_share=True)
                    is not None,
                )
            else:
                user_id = resolve_principal_user_in_session(
                    session,
                    requester.principal,
                    country_id=request.country_id,
                    now=request.requested_at,
                ).user_id
            recorded = record_creates.create_report_run_records(
                session,
                user_id=user_id,
                records=[
                    ReportRunRecordRead(
                        report_run_id=report_run_id,
                        requested_at=request.requested_at,
                        trigger=request.trigger,
                    )
                    for report_run_id in (
                        (request.report_run_id,)
                        if request.report_run_id is not None
                        else record_reads.read_budget_window_year_run_ids(
                            session, budget_window_run_id=request.run_id
                        )
                    )
                ],
            )
            if recorded:
                record_updates.advance_saved_reports_last_run_at(
                    session,
                    user_id=user_id,
                    report_id=request.report_id,
                    requested_at=request.requested_at,
                )
