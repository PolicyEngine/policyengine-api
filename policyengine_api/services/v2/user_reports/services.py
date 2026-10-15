"""Application services for native v2 user-report associations.

Stage 12A anchors saved reports on the requested v1 report output ID. The
owner always comes from the verified session principal (a signed-in user or a
signed-out browser), and v1 references are checked in a short read-only v1
transaction before the v2 transaction opens. Reads never provision a
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
    shared_user_report_read,
    user_report_page,
    user_report_read,
    user_report_update_values,
)
from policyengine_api.services.v2.user_reports.validators import (
    require_owned_user_policy,
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
        principal: AccountPrincipal,
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
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_for_read_in_session(
                session, principal, country_id=country_id
            )
            if owner is None:
                return user_report_page([], offset=offset, limit=limit)
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
        principal: AccountPrincipal,
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
