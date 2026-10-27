"""Application services for native v2 user-report associations.

A saved report names a v2 report, a v1 report output, or both. The owner
always comes from the verified session principal (a signed-in user or a
signed-out browser). Before the v2 transaction opens, a v1 reference is
checked in a short read-only v1 transaction, and a v2 report with the
simulation service, which owns v2 reports. Reads never provision a
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
    require_simulation_reference_checker,
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
    read_user_report_row,
    read_user_report_rows,
)
from policyengine_api.services.v2.user_reports.database_connectors.updates import (
    update_user_report,
)
from policyengine_api.services.v2.user_reports.transformations import (
    owned_user_report_input,
    repointed_report_references,
    shared_user_report_read,
    stored_report_references,
    user_report_page,
    user_report_read,
    user_report_update_values,
)
from policyengine_api.services.v2.user_reports.types import (
    ReportReferences,
    UserReportListing,
)
from policyengine_api.services.v2.user_reports.validators import (
    require_owned_user_policy,
    require_unchanged_references,
    require_user_report,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserReportAssociation
    from policyengine_api.services.v2.associations.types import (
        LegacyReferenceChecker,
        SimulationReferenceChecker,
    )
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
        simulation_references: SimulationReferenceChecker | None = None,
    ) -> None:
        """Open sessions through ``database_session``.

        ``legacy_references`` checks v1 report outputs and
        ``simulation_references`` v2 reports before a write. Saving or
        repointing to a reference whose checker is missing raises
        LegacyReferenceCheckUnavailableError or
        SimulationReferenceCheckUnavailableError.
        """
        self._database_session = database_session
        self._legacy_references = legacy_references
        self._simulation_references = simulation_references

    def _require_references(
        self,
        *,
        country_id: str,
        references: ReportReferences,
        check_legacy_report: bool,
    ) -> None:
        """Check a saved report's references before the v2 transaction opens.

        The v1 report output is checked when ``check_legacy_report`` is set. The
        v2 report is checked whenever there is one, and when there are both,
        it must be the report migrated from that v1 report output.
        """
        if check_legacy_report and references.legacy_report_id is not None:
            require_legacy_reference(
                self._legacy_references,
                LegacyRecordKind.REPORT,
                country_id=country_id,
                legacy_id=references.legacy_report_id,
            )
        if references.report_id is not None:
            require_simulation_reference_checker(
                self._simulation_references
            ).require_report(
                country_id=country_id,
                report_id=references.report_id,
                legacy_report_id=references.legacy_report_id,
            )

    def _stored_references(
        self, *, principal: AccountPrincipal, country_id: str, association_id: UUID
    ) -> ReportReferences:
        """Read the references the principal's saved report holds now."""
        with self._database_session.read() as session:
            owner = resolve_principal_user_for_read_in_session(
                session, principal, country_id=country_id
            )
            return stored_report_references(
                read_owned_user_report(
                    session,
                    user_id=None if owner is None else owner.user_id,
                    country_id=country_id,
                    association_id=association_id,
                )
            )

    def create_user_report(
        self,
        *,
        principal: AccountPrincipal,
        association_input: UserReportCreateFields,
    ) -> UserReportRead:
        """Save a report for the principal, provisioning its v2 user if needed.

        Each supplied reference is checked first: a v1 report output in a
        read-only v1 transaction (LegacyReferenceNotFoundError), and a v2
        report with the simulation service (SimulationReferenceNotFoundError),
        each in the country. Each saved-reform link must name the owner's
        saved policy in the same country, or AssociationLinkNotFoundError is
        raised.
        """
        self._require_references(
            country_id=association_input.country_id,
            references=ReportReferences(
                report_id=association_input.report_id,
                legacy_report_id=association_input.legacy_report_id,
            ),
            check_legacy_report=True,
        )
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session,
                principal,
                country_id=association_input.country_id,
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

        A new ``report_id`` or ``legacy_report_id`` is checked first, as on
        create, together with the reference the saved report keeps: when it
        will hold both, the v2 report must be the one migrated from that v1
        report output (AssociationReferenceConflictError). If the saved report
        changes during that check, AssociationConflictError is raised. A
        supplied saved-reform link must name the owner's saved policy in this
        country. Raise UserReportNotFoundError if the principal has no such
        report in this country.
        """
        checked: ReportReferences | None = None
        if (
            association_input.report_id is not None
            or association_input.legacy_report_id is not None
        ):
            stored = self._stored_references(
                principal=principal,
                country_id=country_id,
                association_id=association_id,
            )
            self._require_references(
                country_id=country_id,
                references=repointed_report_references(stored, association_input),
                check_legacy_report=association_input.legacy_report_id is not None,
            )
            checked = stored
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
            if checked is not None:
                require_unchanged_references(association, checked=checked)
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
