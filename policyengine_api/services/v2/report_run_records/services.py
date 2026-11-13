"""Record each user's requests for v2 report runs.

The report routes record a request once the simulation service has answered
which run it ended on, created or joined: the requesting user's
``user_report_run_associations`` row for that run, written in one
transaction with the user's provisioning (a signed-in identity's user, or a
signed-out browser's unauthenticated user, as any user write provisions
it) and with the ``last_run_at`` of the user's saved reports naming the
report. Before the simulation service is asked, the requester is checked,
so a browser credential that names a signed-in user is refused before
anything is created.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.services.v2.identity.services import (
    find_principal_user_in_session,
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.report_run_records.database_connectors import (
    creates as record_creates,
)
from policyengine_api.services.v2.report_run_records.database_connectors import (
    updates as record_updates,
)
from policyengine_api.services.v2.report_run_records.validators import (
    ReportRunRecordStorageError,
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

    def check_requester(self, principal: AccountPrincipal) -> None:
        """Refuse a principal no record can be written for, before anything starts.

        Nothing is written. Raise StandardUserRequiresSignInError for an
        unauthenticated credential that names a signed-in user, and
        ReportRunRecordStorageError when the database cannot be read.
        """
        with _storage_failures(), self._database_session.read() as session:
            find_principal_user_in_session(session, principal)

    def record(self, principal: AccountPrincipal, request: ReportRunRequest) -> None:
        """Record the principal's request for each run it ended on, in one transaction.

        The principal's user is provisioned if absent. A run the user already
        has a record of keeps it. When this request recorded a run, the
        user's saved reports naming the report take its ``requested_at`` as
        their ``last_run_at`` if it is later. Raise
        StandardUserRequiresSignInError for an unauthenticated credential
        that names a signed-in user, and ReportRunRecordStorageError when the
        database cannot be written.
        """
        with _storage_failures(), self._database_session.transaction() as session:
            user = resolve_principal_user_in_session(
                session,
                principal,
                country_id=request.country_id,
                now=request.requested_at,
            )
            recorded = record_creates.create_report_run_records(
                session,
                user_id=user.user_id,
                report_run_ids=request.report_run_ids,
                requested_at=request.requested_at,
                trigger=request.trigger,
            )
            if recorded:
                record_updates.advance_saved_reports_last_run_at(
                    session,
                    user_id=user.user_id,
                    report_id=request.report_id,
                    requested_at=request.requested_at,
                )
