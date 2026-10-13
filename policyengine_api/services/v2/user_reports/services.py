"""Application services for native v2 user-report associations.

Stage 12A anchors saved reports on the requested v1 report output ID. The
owner always comes from the verified session principal, and v1 references are
checked in a short read-only v1 transaction before the v2 transaction opens.
An optional ``user_policy_id`` must name the same owner's saved policy in the
same country.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlmodel import Session

from policyengine_api.data.v2.models import UserPolicy, UserReportAssociation
from policyengine_api.services.v2.associations.database_connectors.reads import (
    read_association_ids_by_client_ref,
)
from policyengine_api.services.v2.associations.services import (
    import_associations_in_session,
    require_legacy_reference,
    require_unused_client_ref_in_session,
)
from policyengine_api.services.v2.associations.types import (
    AssociationImport,
    LegacyReferenceChecker,
)
from policyengine_api.services.v2.identity.services import (
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.identity.types import UserPrincipal
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
    read_owned_user_report_row,
    read_user_report_rows,
)
from policyengine_api.services.v2.user_reports.database_connectors.updates import (
    update_user_report,
)
from policyengine_api.services.v2.user_reports.database_session import (
    UserReportDatabaseSession,
)
from policyengine_api.services.v2.user_reports.transformations import (
    imported_user_report_input,
    owned_user_report_input,
    user_report_page,
    user_report_read,
    user_report_update_values,
)
from policyengine_api.services.v2.user_reports.types import (
    UserReportCreateFields,
    UserReportImportItem,
    UserReportPage,
    UserReportRead,
    UserReportUpdateInput,
)
from policyengine_api.services.v2.user_reports.validators import (
    require_owned_user_policy,
    require_user_report,
)


def read_owned_user_report(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    association_id: UUID,
) -> UserReportAssociation:
    return require_user_report(
        read_owned_user_report_row(
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
    if user_policy_id is None:
        return
    require_owned_user_policy(
        read_owned_user_policy_exists(
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


def import_user_reports_in_session(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    items: Sequence[UserReportImportItem],
) -> AssociationImport:
    """Insert imported reports idempotently on ``(user_id, client_ref)``.

    ``user_policy_client_ref`` resolves against the owner's saved policies in
    the import country only, including policies inserted earlier in the same
    transaction. An unresolved reference leaves ``user_policy_id`` empty.
    """

    policy_ids = read_association_ids_by_client_ref(
        session,
        UserPolicy,
        user_id=user_id,
        client_refs={
            item.user_policy_client_ref
            for item in items
            if item.user_policy_client_ref is not None
        },
        country_id=country_id,
    )
    return import_associations_in_session(
        session,
        UserReportAssociation,
        user_id=user_id,
        country_id=country_id,
        rows=[
            (
                item.client_ref,
                imported_user_report_input(
                    item,
                    country_id=country_id,
                    user_id=user_id,
                    user_policy_id=(
                        policy_ids.get(item.user_policy_client_ref)
                        if item.user_policy_client_ref is not None
                        else None
                    ),
                ).model_dump(),
            )
            for item in items
        ],
    )


class V2UserReportService:
    """Sequence owner-scoped association operations through explicit sessions."""

    def __init__(
        self,
        database_session: UserReportDatabaseSession,
        legacy_references: LegacyReferenceChecker | None = None,
    ) -> None:
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
        principal: UserPrincipal,
        association_input: UserReportCreateFields,
    ) -> UserReportRead:
        self._require_legacy_report(
            country_id=association_input.country_id,
            legacy_report_id=association_input.legacy_report_id,
        )
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session,
                principal,
                country_id=association_input.country_id,
            )
            require_unused_client_ref_in_session(
                session,
                UserReportAssociation,
                user_id=owner.user_id,
                client_ref=association_input.client_ref,
            )
            validate_linked_user_policy(
                session,
                user_id=owner.user_id,
                country_id=association_input.country_id,
                user_policy_id=association_input.user_policy_id,
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
        principal: UserPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> UserReportRead:
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            return user_report_read(
                read_owned_user_report(
                    session,
                    user_id=owner.user_id,
                    country_id=country_id,
                    association_id=association_id,
                )
            )

    def list_user_reports(
        self,
        *,
        principal: UserPrincipal,
        country_id: str,
        legacy_report_id: int | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> UserReportPage:
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            rows = read_user_report_rows(
                session,
                country_id=country_id,
                user_id=owner.user_id,
                legacy_report_id=legacy_report_id,
                offset=offset,
                limit=limit,
            )
            return user_report_page(rows, offset=offset, limit=limit)

    def patch_user_report(
        self,
        *,
        principal: UserPrincipal,
        country_id: str,
        association_id: UUID,
        association_input: UserReportUpdateInput,
    ) -> UserReportRead:
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
            if "user_policy_id" in association_input.model_fields_set:
                validate_linked_user_policy(
                    session,
                    user_id=owner.user_id,
                    country_id=country_id,
                    user_policy_id=association_input.user_policy_id,
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
        principal: UserPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> None:
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
