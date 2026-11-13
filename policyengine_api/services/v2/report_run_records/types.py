"""Data the report-run record service and its callers exchange.

A user's request for a report run is recorded once per user and run
(``user_report_run_associations``): a user asking again for a run they have
keeps their first record, and its ``requested_at``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from policyengine_api.data.v2.models import ReportRunTrigger
    from policyengine_api.services.v2.identity.types import AccountPrincipal


@dataclass(frozen=True)
class ReportRunRequest:
    """One user's request for a run of a report: what to record.

    ``report_run_ids`` are the report runs the request ended on, created or
    joined; ``requested_at`` is when the Public API received the request,
    the time the user sees; ``trigger`` is ``initial`` for a create and
    ``manual`` for a re-run. ``country_id`` is the report's country, the
    primary country of a signed-in user provisioned by this request.
    """

    country_id: str
    report_id: UUID
    report_run_ids: tuple[UUID, ...]
    requested_at: datetime
    trigger: ReportRunTrigger


@dataclass(frozen=True)
class CheckedRequester:
    """A requester checked before the simulation service is asked.

    ``user_id`` is the user the principal had then, or None when it had none
    yet (a signed-out browser's first write, or a signed-in identity's first
    request), in which case the record provisions one.
    """

    principal: AccountPrincipal
    user_id: UUID | None


@dataclass(frozen=True)
class ReportRunRecordRead:
    """One stored record of a user's request: the run, when, and how."""

    report_run_id: UUID
    requested_at: datetime
    trigger: ReportRunTrigger


class ReportRunRecorder(Protocol):
    """Record the report runs users ask for."""

    def check_requester(self, principal: AccountPrincipal) -> CheckedRequester:
        """Check a principal before anything starts, and name its user if it has one.

        Raise StandardUserRequiresSignInError for an unauthenticated
        credential that names a signed-in user, and ReportRunRecordStorageError
        when the database cannot be read.
        """
        ...

    def record(self, requester: CheckedRequester, request: ReportRunRequest) -> None:
        """Record the request for the user the check found, or a new one if none.

        The user's saved reports naming the report get the request's time as
        their ``last_run_at`` when it is newer. Raise RequesterUserGoneError
        when the user the check found no longer exists.
        """
        ...
