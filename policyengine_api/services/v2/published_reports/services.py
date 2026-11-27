"""Publish saved reports as public pages, and read them publicly.

An author or admin publishes one of their saved reports, showing one
succeeded run of the report it names (a budget window's budget-window run),
with a summary, authors, tags and content of its own. The route requires the
user type; this service requires that the principal owns the saved report,
in the country, and never provisions a signed-out browser's user. The owner
edits the page's fields, moves it to another succeeded run of the report as
a new version, reads it with every version, and withdraws it, which deletes
it with its versions. A saved report is published at most once, and a page
shows each run at most once.

Anyone reads a published report by its saved report's ID, with no
credential: the page, the saved report's presentation as a shared report
shows it, and the report with the run of its newest version, or of the
version the reader names while the author shows past versions. The report
is read as ``GET /v2/reports/{id}`` reads it for nobody, then labelled with
the saved report's name; the owner, the owner's notes and saved-reform IDs
are never read out.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.data.v2.models.base import utc_now
from policyengine_api.services.v2.identity.services import (
    resolve_principal_user_for_read_in_session,
)
from policyengine_api.services.v2.published_reports.database_connectors import (
    reads as publication_reads,
)
from policyengine_api.services.v2.published_reports.database_connectors.creates import (
    create_publication,
    create_publication_version,
)
from policyengine_api.services.v2.published_reports.database_connectors.deletes import (
    delete_publication,
)
from policyengine_api.services.v2.published_reports.database_connectors.updates import (
    update_publication,
)
from policyengine_api.services.v2.published_reports.transformations import (
    publication_read,
    publication_update_values,
    publication_values,
    publication_version_read,
    published_report_read,
    published_run,
    published_saved_report_read,
)
from policyengine_api.services.v2.published_reports.types import ShownVersions
from policyengine_api.services.v2.published_reports.validators import (
    PublicationNotFoundError,
    PublishedReportNotFoundError,
    PublishedReportStorageError,
    readable_versions,
    require_new_run,
    require_publication,
    require_publishable,
    require_published_report,
    require_readable_version,
    require_report_row,
    require_succeeded_run,
    require_unpublished,
    require_versions,
)
from policyengine_api.services.v2.stored_reports.transformations import report_kind
from policyengine_api.services.v2.user_reports.database_connectors.reads import (
    lock_owned_user_report_row,
    read_owned_user_policy_row,
    read_owned_user_report_row,
)
from policyengine_api.services.v2.user_reports.transformations import (
    shared_user_report_read,
)
from policyengine_api.services.v2.user_reports.validators import require_user_report

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import (
        PublishedReport,
        UserReportAssociation,
    )
    from policyengine_api.services.v2.identity.types import AccountPrincipal
    from policyengine_api.services.v2.published_reports.database_session import (
        PublishedReportDatabaseSession,
    )
    from policyengine_api.services.v2.published_reports.types import (
        PublicationCreateInput,
        PublicationRead,
        PublicationUpdateInput,
        PublicationVersionInput,
        PublicationVersionRead,
        PublishedReportRead,
        PublishedReportReader,
        PublishedRun,
    )


@contextmanager
def _storage_failures() -> Iterator[None]:
    """Raise PublishedReportStorageError for a failed database read."""
    try:
        yield
    except SQLAlchemyError as error:
        msg = "V2 report storage is unavailable"
        raise PublishedReportStorageError(msg) from error


def _owned_user_report(
    session: Session,
    principal: AccountPrincipal,
    *,
    country_id: str,
    user_report_id: UUID,
    lock: bool = False,
) -> UserReportAssociation:
    """Return the principal's saved report in the country, or raise not found.

    With ``lock``, the row stays locked until the transaction ends, as a
    publish needs. A signed-out browser's user is never provisioned: one
    not stored yet owns nothing.
    """
    owner = resolve_principal_user_for_read_in_session(
        session, principal, country_id=country_id
    )
    if owner is None:
        association = None
    else:
        read_saved_report = (
            lock_owned_user_report_row if lock else read_owned_user_report_row
        )
        association = read_saved_report(
            session,
            user_id=owner.user_id,
            country_id=country_id,
            association_id=user_report_id,
        )
    return require_user_report(association, association_id=user_report_id)


def _versions(session: Session, user_report_id: UUID) -> list[PublicationVersionRead]:
    """Return the published report's versions, newest first, with their runs."""
    rows = publication_reads.read_publication_version_rows(
        session, user_report_id=user_report_id
    )
    window_first_years = publication_reads.read_window_first_years(
        session,
        budget_window_run_ids=[
            version.budget_window_run_id
            for version, _report_run in rows
            if version.budget_window_run_id is not None
        ],
    )
    return [
        publication_version_read(version, report_run, window_first_years)
        for version, report_run in rows
    ]


def _succeeded_run(session: Session, *, report_id: UUID, run_id: UUID) -> PublishedRun:
    """Return the report's succeeded run ``run_id``, as a version names it.

    A budget window's runs are its budget-window runs; any other report's,
    its own report runs. Raise PublicationRunNotFoundError when the report
    has no such run, and PublicationRunNotSucceededError unless it has
    succeeded.
    """
    kind = report_kind(
        require_report_row(
            publication_reads.read_report_row(session, report_id=report_id),
            report_id=report_id,
        )
    )
    read_status = (
        publication_reads.read_budget_window_run_status
        if kind == "budget_window"
        else publication_reads.read_report_run_status
    )
    require_succeeded_run(
        read_status(session, report_id=report_id, run_id=run_id),
        report_id=report_id,
        run_id=run_id,
    )
    return published_run(kind, run_id)


class V2PublishedReportService:
    """Publish the owner's saved reports, and read published reports publicly."""

    def __init__(
        self,
        database_session: PublishedReportDatabaseSession,
        *,
        reports: PublishedReportReader,
    ) -> None:
        """Open sessions through ``database_session``; read reports through ``reports``.

        ``reports`` reads a report with one of its runs, as the report
        service does for ``GET /v2/reports/{id}``.
        """
        self._database_session = database_session
        self._reports = reports

    def _owned_page(
        self, session: Session, publication: PublishedReport, *, country_id: str
    ) -> PublicationRead:
        """Return the owner's published report with its versions, as read now.

        Raise PublicationNotFoundError when it has none: it was withdrawn
        between this read's statements.
        """
        return publication_read(
            publication,
            country_id=country_id,
            versions=require_versions(
                _versions(session, publication.user_report_id),
                missing=PublicationNotFoundError(
                    f"Saved report {publication.user_report_id} is not published"
                ),
            ),
        )

    def _owned_publication(
        self,
        session: Session,
        principal: AccountPrincipal,
        *,
        country_id: str,
        user_report_id: UUID,
        lock: bool = False,
    ) -> tuple[UserReportAssociation, PublishedReport]:
        """Return the principal's saved report and its published report.

        With ``lock``, the published report stays locked until the transaction
        ends, as an edit, a move and a withdrawal need. Raise
        UserReportNotFoundError when the principal has no such saved report in
        the country, and PublicationNotFoundError when it isn't published.
        """
        association = _owned_user_report(
            session, principal, country_id=country_id, user_report_id=user_report_id
        )
        read_page = (
            publication_reads.lock_publication_row
            if lock
            else publication_reads.read_publication_row
        )
        publication = require_publication(
            read_page(session, user_report_id=user_report_id),
            user_report_id=user_report_id,
        )
        return association, publication

    def publish_report(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        user_report_id: UUID,
        publication_input: PublicationCreateInput,
    ) -> PublicationRead:
        """Publish the principal's saved report, showing the run the input names.

        Raise UserReportNotFoundError when the principal has no such saved
        report in the country, UnpublishableUserReportError when it names
        only a v1 report output or has no name, PublicationExistsError when
        it is published already, PublicationRunNotFoundError when the run
        isn't one of its report's runs, and PublicationRunNotSucceededError
        unless the run has succeeded.
        """
        with self._database_session.transaction() as session:
            association = _owned_user_report(
                session,
                principal,
                country_id=country_id,
                user_report_id=user_report_id,
                lock=True,
            )
            report_id = require_publishable(association)
            require_unpublished(
                publication_reads.read_publication_row(
                    session, user_report_id=user_report_id
                ),
                user_report_id=user_report_id,
            )
            run = _succeeded_run(
                session, report_id=report_id, run_id=publication_input.run_id
            )
            published_at = utc_now()
            publication = create_publication(
                session,
                user_report_id=user_report_id,
                report_id=report_id,
                values=publication_values(publication_input),
                published_at=published_at,
            )
            create_publication_version(
                session,
                user_report_id=user_report_id,
                run=run,
                published_at=published_at,
            )
            return publication_read(
                publication,
                country_id=country_id,
                versions=_versions(session, user_report_id),
            )

    def get_publication(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        user_report_id: UUID,
    ) -> PublicationRead:
        """Return the principal's published report with every version, newest first.

        Raise UserReportNotFoundError when the principal has no such saved
        report in the country, and PublicationNotFoundError when it isn't
        published.
        """
        with self._database_session.transaction() as session:
            _association, publication = self._owned_publication(
                session,
                principal,
                country_id=country_id,
                user_report_id=user_report_id,
            )
            return self._owned_page(session, publication, country_id=country_id)

    def update_publication(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        user_report_id: UUID,
        publication_input: PublicationUpdateInput,
    ) -> PublicationRead:
        """Set the fields the edit sends on the principal's published report.

        Raise UserReportNotFoundError when the principal has no such saved
        report in the country, and PublicationNotFoundError when it isn't
        published.
        """
        with self._database_session.transaction() as session:
            _association, publication = self._owned_publication(
                session,
                principal,
                country_id=country_id,
                user_report_id=user_report_id,
                lock=True,
            )
            update_publication(
                session,
                publication,
                values=publication_update_values(publication_input),
                updated_at=utc_now(),
            )
            return self._owned_page(session, publication, country_id=country_id)

    def add_publication_version(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        user_report_id: UUID,
        version_input: PublicationVersionInput,
    ) -> PublicationRead:
        """Move the principal's published report to another run, as its new version.

        Raise UserReportNotFoundError when the principal has no such saved
        report in the country, PublicationNotFoundError when it isn't
        published, PublicationRunAlreadyShownError when a version shows the
        run, PublicationRunNotFoundError when the run isn't one of its
        report's runs, and PublicationRunNotSucceededError unless the run
        has succeeded.
        """
        with self._database_session.transaction() as session:
            _association, publication = self._owned_publication(
                session,
                principal,
                country_id=country_id,
                user_report_id=user_report_id,
                lock=True,
            )
            require_new_run(
                require_versions(
                    _versions(session, user_report_id),
                    missing=PublicationNotFoundError(
                        f"Saved report {user_report_id} is not published"
                    ),
                ),
                run_id=version_input.run_id,
            )
            run = _succeeded_run(
                session,
                report_id=publication.report_id,
                run_id=version_input.run_id,
            )
            moved_at = utc_now()
            create_publication_version(
                session,
                user_report_id=user_report_id,
                run=run,
                published_at=moved_at,
            )
            update_publication(session, publication, values={}, updated_at=moved_at)
            return self._owned_page(session, publication, country_id=country_id)

    def withdraw_publication(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        user_report_id: UUID,
    ) -> None:
        """Delete the principal's published report with its versions.

        Raise UserReportNotFoundError when the principal has no such saved
        report in the country, and PublicationNotFoundError when it isn't
        published.
        """
        with self._database_session.transaction() as session:
            _association, publication = self._owned_publication(
                session,
                principal,
                country_id=country_id,
                user_report_id=user_report_id,
                lock=True,
            )
            delete_publication(session, publication)

    def get_published_report(
        self,
        *,
        country_id: str,
        user_report_id: UUID,
        version_id: UUID | None = None,
    ) -> PublishedReportRead:
        """Return a published report as anyone reads it, with no credential.

        Its run is its newest version's, or ``version_id``'s while the author
        shows past versions. Raise PublishedReportNotFoundError when the
        country has no such published report, PublishedVersionNotFoundError
        when ``version_id`` names none of the versions a reader may open, and
        PublishedReportStorageError when the database can't be read; reading
        the report raises what the report service's read raises.
        """
        with _storage_failures(), self._database_session.read() as session:
            publication, association = require_published_report(
                publication_reads.read_published_report_rows(
                    session, country_id=country_id, user_report_id=user_report_id
                ),
                user_report_id=user_report_id,
                country_id=country_id,
            )
            page = publication_read(
                publication,
                country_id=country_id,
                versions=require_versions(
                    _versions(session, user_report_id),
                    missing=PublishedReportNotFoundError(
                        f"No published report {user_report_id} in {country_id}"
                    ),
                ),
            )
            baseline_user_policy_id = association.baseline_user_policy_id
            saved_report = published_saved_report_read(
                shared_user_report_read(
                    association,
                    baseline_reform=(
                        None
                        if baseline_user_policy_id is None
                        else read_owned_user_policy_row(
                            session,
                            user_id=association.user_id,
                            country_id=country_id,
                            user_policy_id=baseline_user_policy_id,
                        )
                    ),
                )
            )
            title = association.name
            report_id = publication.report_id
        readable = readable_versions(
            page.versions, show_past_versions=page.show_past_versions
        )
        version = require_readable_version(readable, version_id=version_id)
        report = self._reports.get_report(
            country_id=country_id,
            report_id=report_id,
            run_id=version.run_id,
            requester=None,
        )
        return published_report_read(
            page,
            title=title,
            saved_report=saved_report,
            shown=ShownVersions(version=version, readable=readable),
            report=report,
        )
