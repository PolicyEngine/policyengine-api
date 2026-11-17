"""Reports as the requesting user sees them.

A report's label and description are the requesting user's saved report's,
and a report the user asked to run is read with the run of their newest
request in place of its default. ``requesters_view`` gives that view of the
rows the report service read; it moved here from
``policyengine_api.services.v2.stored_reports.services`` unchanged.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from policyengine_api.services.v2.identity.services import (
    find_principal_user_in_session,
)
from policyengine_api.services.v2.stored_reports.database_connectors import (
    reads_requests as request_reads,
)
from policyengine_api.services.v2.stored_reports.database_connectors.reads import (
    read_budget_window_years,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.services.v2.identity.types import AccountPrincipal
    from policyengine_api.services.v2.stored_reports.types import (
        StoredReportRows,
    )


def _viewer_user_id(
    session: Session,
    *,
    requester: AccountPrincipal | None,
    recorded_user_id: UUID | None,
) -> UUID | None:
    """Return the ID of the user a read is for.

    That is ``recorded_user_id`` when a request was just recorded for it, or
    else the requester's stored user's, or None.
    """
    if recorded_user_id is not None:
        return recorded_user_id
    if requester is None:
        return None
    user = find_principal_user_in_session(session, requester)
    return None if user is None else user.user_id


def requesters_view(
    session: Session,
    rows: Sequence[StoredReportRows],
    *,
    requester: AccountPrincipal | None,
    recorded_user_id: UUID | None = None,
    with_requested_runs: bool,
) -> list[StoredReportRows]:
    """Return the reports as the requester sees them.

    The requester's stored user is looked up, unless ``recorded_user_id``
    names the user a request was just recorded for. Each report takes its
    label and description from that user's saved report of it. With
    ``with_requested_runs``, a report the user asked to run
    is read with the run of their newest request in place of its default (a
    budget window's with that year's budget-window run and its years). A
    request naming no user, or a user not stored yet, sees each report's
    default run and no label. Raise StandardUserRequiresSignInError for an
    unauthenticated credential that names a signed-in user.
    """
    user_id = _viewer_user_id(
        session, requester=requester, recorded_user_id=recorded_user_id
    )
    if user_id is None or not rows:
        return list(rows)
    report_ids = [stored.report.id for stored in rows]
    labels = request_reads.read_saved_report_labels(
        session, user_id=user_id, report_ids=report_ids
    )
    requested_runs = (
        request_reads.read_requested_report_runs(
            session, user_id=user_id, report_ids=report_ids
        )
        if with_requested_runs
        else {}
    )
    window_run_ids = [
        run.budget_window_run_id
        for run in requested_runs.values()
        if run.budget_window_run_id is not None
    ]
    window_runs = request_reads.read_budget_window_runs_by_id(
        session, budget_window_run_ids=window_run_ids
    )
    window_years = read_budget_window_years(session, window_run_ids)
    viewed = []
    for stored in rows:
        name, description = labels.get(stored.report.id, (None, None))
        seen = replace(
            stored, saved_report_name=name, saved_report_description=description
        )
        requested = requested_runs.get(stored.report.id)
        if requested is not None and requested.budget_window_run_id is None:
            seen = replace(seen, run=requested)
        elif requested is not None and requested.budget_window_run_id in window_runs:
            window_run_id = requested.budget_window_run_id
            seen = replace(
                seen,
                budget_window_run=window_runs[window_run_id],
                budget_window_years=window_years.get(window_run_id, ()),
            )
        viewed.append(seen)
    return viewed
