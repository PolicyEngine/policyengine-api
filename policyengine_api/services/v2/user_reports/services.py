"""Application services for native v2 user-report associations.

A saved report names a detailed-save report (``report_id``) or a v1 report
output (``legacy_report_id``), never both: v1 report numbers are not
connected to detailed-save reports, and only the production migration writes
saved reports holding both. A detailed-save report is checked with a SELECT
in the write's own transaction; one deleted before the write commits is
refused by the ``RESTRICT`` foreign key, which is answered as not found too.
A saved report naming one gives that report's own budget window as
``budget_window_years``, or none for a report without a window of two or
more years.
The owner always comes from the verified session principal (a signed-in user
or a signed-out browser), and v1 references are checked in a short read-only
v1 transaction before the v2 transaction opens. Reads never provision a
browser's unauthenticated user; one that does not exist yet owns no records.
An optional ``user_policy_id`` (the saved reform the report was run from) and
an optional ``baseline_user_policy_id`` (the saved reform it was compared with)
must each name the same owner's saved policy in the same country.

A saved report's ID is also its shareable link: anyone holding it can read
the report without a credential, minus the owner and the owner's links.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.associations.services import (
    require_legacy_reference,
)
from policyengine_api.services.v2.associations.validators import (
    require_one_reference,
)
from policyengine_api.services.v2.identity.services import (
    resolve_principal_user_for_read_in_session,
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordKind
from policyengine_api.services.v2.user_reports.database_connectors.creates import (
    create_user_report,
)
from policyengine_api.services.v2.user_reports.database_connectors.deletes import (
    delete_user_report,
)
from policyengine_api.services.v2.user_reports.database_connectors.reads import (
    read_all_user_report_rows,
    read_owned_user_policy_exists,
    read_owned_user_policy_row,
    read_owned_user_report_row,
    read_report_budget_window_size,
    read_report_exists,
    read_user_report_row,
    read_user_report_rows,
)
from policyengine_api.services.v2.user_reports.database_connectors.updates import (
    update_user_report,
)
from policyengine_api.services.v2.user_reports.transformations import (
    owned_user_report_input,
    shared_user_report_read,
    user_report_page,
    user_report_read,
    user_report_update_values,
)
from policyengine_api.services.v2.user_reports.types import UserReportListing
from policyengine_api.services.v2.user_reports.validators import (
    require_matching_budget_window,
    require_owned_user_policy,
    require_stored_report,
    require_user_report,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserReportAssociation
    from policyengine_api.services.v2.associations.types import LegacyReferenceChecker
    from policyengine_api.services.v2.identity.types import AccountPrincipal
    from policyengine_api.services.v2.user_reports.database_session import (
        UserReportDatabaseSession,
    )
    from policyengine_api.services.v2.user_reports.types import (
        SharedUserReportRead,
        UserReportCreateFields,
        UserReportPage,
        UserReportRead,
        UserReportUpdateInput,
    )


def read_owned_user_report(
    session: Session,
    *,
    user_id: UUID | None,
    country_id: str,
    association_id: UUID,
) -> UserReportAssociation:
    """``user_id`` is None for an unauthenticated user that owns nothing yet."""
    return require_user_report(
        None
        if user_id is None
        else read_owned_user_report_row(
            session,
            user_id=user_id,
            country_id=country_id,
            association_id=association_id,
        ),
        association_id=association_id,
    )


def validate_linked_user_policy(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    user_policy_id: UUID | None,
) -> None:
    """Check that a saved-reform link names the owner's saved policy in this country.

    A None link passes; otherwise raise AssociationLinkNotFoundError.
    """
    if user_policy_id is None:
        return
    require_owned_user_policy(
        owned=read_owned_user_policy_exists(
            session,
            user_id=user_id,
            country_id=country_id,
            user_policy_id=user_policy_id,
        ),
        user_policy_id=user_policy_id,
    )


def validate_stored_report(
    session: Session, *, country_id: str, report_id: UUID | None
) -> None:
    """Check, in the write's transaction, that a named report is stored in the country.

    A None ``report_id`` passes; otherwise raise AssociationReportNotFoundError.
    """
    if report_id is None:
        return
    require_stored_report(
        stored=read_report_exists(session, country_id=country_id, report_id=report_id),
        report_id=report_id,
        country_id=country_id,
    )


def validate_saved_budget_window(
    session: Session,
    *,
    country_id: str,
    report_id: UUID | None,
    budget_window_years: int | None,
) -> None:
    """Check, in the write's transaction, the saved window against the report's.

    A None ``report_id`` passes: a v1 report output stores no window of its
    own. Otherwise raise AssociationBudgetWindowConflictError unless
    ``budget_window_years`` agrees with the report's budget window.
    """
    if report_id is None:
        return
    require_matching_budget_window(
        report_id=report_id,
        budget_window_size=read_report_budget_window_size(
            session, country_id=country_id, report_id=report_id
        ),
        budget_window_years=budget_window_years,
    )


def validate_saved_budget_window_after_update(
    session: Session,
    *,
    association: UserReportAssociation,
    association_input: UserReportUpdateInput,
) -> None:
    """Check the window the update leaves against the report it leaves named.

    Only an update that names a report or a window is checked, so a record
    saved before the check can still be renamed.
    """
    supplied = association_input.model_fields_set
    if not supplied.intersection({"report_id", "budget_window_years"}):
        return
    validate_saved_budget_window(
        session,
        country_id=association.country_id,
        report_id=(
            association_input.report_id
            if "report_id" in supplied
            else association.report_id
        ),
        budget_window_years=(
            association_input.budget_window_years
            if "budget_window_years" in supplied
            else association.budget_window_years
        ),
    )


def require_one_report_after_update(
    association: UserReportAssociation, association_input: UserReportUpdateInput
) -> None:
    """Raise AssociationReferenceConflictError if the update leaves both references.

    Only an update that names a reference is checked, so a record the
    production migration saved with both can still be renamed.
    """
    supplied = association_input.model_fields_set
    if not supplied.intersection({"report_id", "legacy_report_id"}):
        return
    require_one_reference(
        "report",
        detailed_save_id=(
            association_input.report_id
            if "report_id" in supplied
            else association.report_id
        ),
        legacy_id=(
            association_input.legacy_report_id
            if "legacy_report_id" in supplied
            else association.legacy_report_id
        ),
    )


def read_all_user_reports(
    session: Session, *, user_id: UUID
) -> tuple[UserReportRead, ...]:
    """Return every report association owned by a user, across countries."""
    return tuple(
        user_report_read(row)
        for row in read_all_user_report_rows(session, user_id=user_id)
    )


class V2UserReportService:
    """Sequence owner-scoped association operations through explicit sessions."""

    def __init__(
        self,
        database_session: UserReportDatabaseSession,
        legacy_references: LegacyReferenceChecker | None = None,
    ) -> None:
        """Open sessions through ``database_session``.

        ``legacy_references`` checks v1 report outputs before a write. Without
        it, creating a saved report or repointing one raises
        LegacyReferenceCheckUnavailableError.
        """
        self._database_session = database_session
        self._legacy_references = legacy_references

    def _require_legacy_report(self, *, country_id: str, legacy_report_id: int) -> None:
        require_legacy_reference(
            self._legacy_references,
            LegacyRecordKind.REPORT,
            country_id=country_id,
            legacy_id=legacy_report_id,
        )

    def create_user_report(
        self,
        *,
        principal: AccountPrincipal,
        association_input: UserReportCreateFields,
    ) -> UserReportRead:
        """Save a report for the principal, provisioning its v2 user if needed.

        A request naming both a report_id and a legacy_report_id raises
        AssociationReferenceConflictError. A v1 report is checked first, in a
        read-only v1 transaction, and LegacyReferenceNotFoundError is raised
        if it does not exist in the country; a detailed-save report is
        checked in the write's transaction, and
        AssociationReportNotFoundError is raised if the country has none, or
        AssociationBudgetWindowConflictError if ``budget_window_years``
        disagrees with its budget window. Each saved-reform link must name the
        owner's saved policy in the same country, or
        AssociationLinkNotFoundError is raised.
        """
        country_id = association_input.country_id
        require_one_reference(
            "report",
            detailed_save_id=association_input.report_id,
            legacy_id=association_input.legacy_report_id,
        )
        if association_input.legacy_report_id is not None:
            self._require_legacy_report(
                country_id=country_id,
                legacy_report_id=association_input.legacy_report_id,
            )
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session,
                principal,
                country_id=country_id,
            )
            validate_stored_report(
                session, country_id=country_id, report_id=association_input.report_id
            )
            validate_saved_budget_window(
                session,
                country_id=country_id,
                report_id=association_input.report_id,
                budget_window_years=association_input.budget_window_years,
            )
            for linked_user_policy_id in (
                association_input.user_policy_id,
                association_input.baseline_user_policy_id,
            ):
                validate_linked_user_policy(
                    session,
                    user_id=owner.user_id,
                    country_id=association_input.country_id,
                    user_policy_id=linked_user_policy_id,
                )
            return user_report_read(
                create_user_report(
                    session,
                    owned_user_report_input(association_input, user_id=owner.user_id),
                )
            )

    def get_user_report(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> UserReportRead:
        """Return the principal's saved report, or raise UserReportNotFoundError.

        The report must be in this country. A signed-out browser that has never
        saved anything owns nothing, and is not provisioned by the read.
        """
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_for_read_in_session(
                session, principal, country_id=country_id
            )
            return user_report_read(
                read_owned_user_report(
                    session,
                    user_id=None if owner is None else owner.user_id,
                    country_id=country_id,
                    association_id=association_id,
                )
            )

    def get_shared_user_report(
        self,
        *,
        country_id: str,
        association_id: UUID,
    ) -> SharedUserReportRead:
        """Read a saved report for anyone holding its link; no credential."""
        with self._database_session.transaction() as session:
            association = require_user_report(
                read_user_report_row(
                    session,
                    country_id=country_id,
                    association_id=association_id,
                ),
                association_id=association_id,
            )
            baseline_user_policy_id = association.baseline_user_policy_id
            return shared_user_report_read(
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

    def list_user_reports(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        legacy_report_id: int | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> UserReportPage:
        """Return a page of the principal's saved reports in this country.

        With ``legacy_report_id``, only saves of that v1 report output are listed.
        A signed-out browser that has never saved anything gets an empty page and
        is not provisioned.
        """
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_for_read_in_session(
                session, principal, country_id=country_id
            )
            if owner is None:
                return user_report_page([], offset=offset, limit=limit)
            rows = read_user_report_rows(
                session,
                UserReportListing(
                    country_id=country_id,
                    user_id=owner.user_id,
                    legacy_report_id=legacy_report_id,
                    offset=offset,
                    limit=limit,
                ),
            )
            return user_report_page(rows, offset=offset, limit=limit)

    def patch_user_report(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
        association_input: UserReportUpdateInput,
    ) -> UserReportRead:
        """Update the supplied fields of one of the principal's saved reports.

        A new ``legacy_report_id`` is checked in v1 first and a new
        ``report_id`` in the write's transaction, as on create, and a supplied
        saved-reform link must name the owner's saved policy in this country.
        Raise AssociationReferenceConflictError when the update would leave
        the saved report naming both, AssociationBudgetWindowConflictError
        when it would leave a ``budget_window_years`` that disagrees with the
        named report's budget window, and UserReportNotFoundError if the
        principal has no such report in this country.
        """
        require_one_reference(
            "report",
            detailed_save_id=association_input.report_id,
            legacy_id=association_input.legacy_report_id,
        )
        if association_input.legacy_report_id is not None:
            self._require_legacy_report(
                country_id=country_id,
                legacy_report_id=association_input.legacy_report_id,
            )
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            association = read_owned_user_report(
                session,
                user_id=owner.user_id,
                country_id=country_id,
                association_id=association_id,
            )
            require_one_report_after_update(association, association_input)
            validate_stored_report(
                session, country_id=country_id, report_id=association_input.report_id
            )
            validate_saved_budget_window_after_update(
                session, association=association, association_input=association_input
            )
            for link_field in ("user_policy_id", "baseline_user_policy_id"):
                if link_field in association_input.model_fields_set:
                    validate_linked_user_policy(
                        session,
                        user_id=owner.user_id,
                        country_id=country_id,
                        user_policy_id=getattr(association_input, link_field),
                    )
            return user_report_read(
                update_user_report(
                    session,
                    association,
                    user_report_update_values(association_input),
                )
            )

    def delete_user_report(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> None:
        """Delete one of the principal's saved reports in this country.

        Raise UserReportNotFoundError if the principal has no such report.
        """
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            delete_user_report(
                session,
                read_owned_user_report(
                    session,
                    user_id=owner.user_id,
                    country_id=country_id,
                    association_id=association_id,
                ),
            )
