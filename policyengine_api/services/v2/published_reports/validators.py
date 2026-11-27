"""Checks and typed errors for publishing saved reports and reading them publicly.

The owner's errors extend the saved-item errors the user routes answer: not
found is 404 and a conflict with stored state 409. The public read's are its
own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import ReportRunStatus
from policyengine_api.services.v2.associations.validators import (
    AssociationConflictError,
    AssociationNotFoundError,
)
from policyengine_api.services.v2.user_reports.validators import is_blank_name

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from policyengine_api.data.v2.models import (
        PublishedReport,
        Report,
        UserReportAssociation,
    )
    from policyengine_api.services.v2.published_reports.types import (
        PublicationVersionRead,
    )


class PublicationNotFoundError(AssociationNotFoundError):
    """The owner's saved report is not published (404)."""


class PublicationExistsError(AssociationConflictError):
    """The saved report is already published (409)."""


class UnpublishableUserReportError(AssociationConflictError):
    """The saved report names no detailed-save report, or has no name (409)."""


class PublicationRunNotFoundError(AssociationNotFoundError):
    """The run is not one of the saved report's report's runs (404)."""


class PublicationRunNotSucceededError(AssociationConflictError):
    """The run has not succeeded, so it has no results to show (409)."""


class PublicationRunAlreadyShownError(AssociationConflictError):
    """The published report has shown the run already (409)."""


class PublishedReportNotFoundError(LookupError):
    """No published report has this ID in this country (404)."""


class PublishedVersionNotFoundError(LookupError):
    """The published report has no version with this ID that readers may open (404)."""


class PublishedReportStorageError(RuntimeError):
    """The database could not be read for a published report (503)."""


def require_publishable(association: UserReportAssociation) -> UUID:
    """Return the detailed-save report a saved report names, if it can be published.

    Raise UnpublishableUserReportError for a saved report that names only a
    v1 report output, or has no name, the page's title, or only blanks.
    """
    if association.report_id is None:
        msg = (
            f"Saved report {association.id} names only a v1 report output; "
            "only a saved report of a detailed-save report can be published"
        )
        raise UnpublishableUserReportError(msg)
    if is_blank_name(association.name):
        msg = (
            f"Saved report {association.id} has no name, which its published "
            "page shows as its title; name it first"
        )
        raise UnpublishableUserReportError(msg)
    return association.report_id


def require_unpublished(
    publication: PublishedReport | None, *, user_report_id: UUID
) -> None:
    """Raise PublicationExistsError when the saved report is published."""
    if publication is not None:
        msg = (
            f"Saved report {user_report_id} is already published; edit it, or "
            "move it to another run as a new version"
        )
        raise PublicationExistsError(msg)


def require_publication(
    publication: PublishedReport | None, *, user_report_id: UUID
) -> PublishedReport:
    """Return the saved report's publication, or raise PublicationNotFoundError."""
    if publication is None:
        msg = f"Saved report {user_report_id} is not published"
        raise PublicationNotFoundError(msg)
    return publication


def require_report_row(report: Report | None, *, report_id: UUID) -> Report:
    """Return the saved report's report, or raise PublicationRunNotFoundError.

    A saved report's foreign key keeps its report, so this is never None
    unless the database was changed by hand.
    """
    if report is None:
        msg = f"Report {report_id} was not found, so it has no runs"
        raise PublicationRunNotFoundError(msg)
    return report


def require_succeeded_run(
    status: ReportRunStatus | None, *, report_id: UUID, run_id: UUID
) -> None:
    """Check a run's status, read from the report's own runs.

    Raise PublicationRunNotFoundError when the report has no such run (None),
    and PublicationRunNotSucceededError unless it has succeeded.
    """
    if status is None:
        msg = f"Report {report_id} has no run {run_id}"
        raise PublicationRunNotFoundError(msg)
    if status is not ReportRunStatus.SUCCEEDED:
        msg = (
            f"Run {run_id} is {status.value}; only a succeeded run, which has "
            "results, can be published"
        )
        raise PublicationRunNotSucceededError(msg)


def require_new_run(
    versions: Sequence[PublicationVersionRead], *, run_id: UUID
) -> None:
    """Raise PublicationRunAlreadyShownError when a version shows the run."""
    if any(version.run_id == run_id for version in versions):
        msg = f"The published report has shown run {run_id} already"
        raise PublicationRunAlreadyShownError(msg)


def require_published_report(
    found: tuple[PublishedReport, UserReportAssociation] | None,
    *,
    user_report_id: UUID,
    country_id: str,
) -> tuple[PublishedReport, UserReportAssociation]:
    """Return a published report and its saved report, or raise not found."""
    if found is None:
        msg = f"No published report {user_report_id} in {country_id}"
        raise PublishedReportNotFoundError(msg)
    return found


def require_versions(
    versions: Sequence[PublicationVersionRead], *, missing: Exception
) -> Sequence[PublicationVersionRead]:
    """Return a published report's versions, or raise ``missing`` when there are none.

    A published report always has a version; a read finds none only when the
    page was withdrawn, or its saved report deleted, between its statements.
    """
    if not versions:
        raise missing
    return versions


def readable_versions(
    versions: Sequence[PublicationVersionRead], *, show_past_versions: bool
) -> tuple[PublicationVersionRead, ...]:
    """Return the versions a reader may open, newest first.

    That is every version while the author shows past versions, else the
    newest alone. ``versions`` is newest first, and never empty.
    """
    return tuple(versions) if show_past_versions else (versions[0],)


def require_readable_version(
    readable: Sequence[PublicationVersionRead], *, version_id: UUID | None
) -> PublicationVersionRead:
    """Return the version to read: ``version_id``, else the newest.

    Raise PublishedVersionNotFoundError when ``version_id`` names none of
    the versions a reader may open.
    """
    if version_id is None:
        return readable[0]
    for version in readable:
        if version.id == version_id:
            return version
    msg = f"The published report has no version {version_id} that readers may open"
    raise PublishedVersionNotFoundError(msg)
