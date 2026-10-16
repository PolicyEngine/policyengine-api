"""Application services for native v2 user-household associations.

The owner always comes from the verified session principal: a signed-in user
or a signed-out browser. Reads never provision a browser's unauthenticated
user; one that does not exist yet owns no records. v1 references are checked
in a short read-only v1 transaction before the v2 transaction opens.
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
from policyengine_api.services.v2.user_households.database_connectors.creates import (
    create_user_household,
)
from policyengine_api.services.v2.user_households.database_connectors.deletes import (
    delete_user_household,
)
from policyengine_api.services.v2.user_households.database_connectors.reads import (
    read_all_user_household_rows,
    read_copied_household_ids,
    read_household_for_association,
    read_owned_user_household_row,
    read_user_household_rows,
)
from policyengine_api.services.v2.user_households.database_connectors.updates import (
    update_user_household,
)
from policyengine_api.services.v2.user_households.transformations import (
    owned_user_household_input,
    user_household_page,
    user_household_read,
)
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdFilter,
    UserHouseholdListing,
)
from policyengine_api.services.v2.user_households.validators import (
    require_user_household,
    resolve_association_household_id,
    validate_association_household,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserHouseholdAssociation
    from policyengine_api.services.v2.associations.types import LegacyReferenceChecker
    from policyengine_api.services.v2.identity.types import AccountPrincipal
    from policyengine_api.services.v2.user_households.database_session import (
        UserHouseholdDatabaseSession,
    )
    from policyengine_api.services.v2.user_households.types import (
        UserHouseholdCreateFields,
        UserHouseholdPage,
        UserHouseholdRead,
        UserHouseholdUpdateInput,
    )


def read_owned_user_household(
    session: Session,
    *,
    user_id: UUID | None,
    country_id: str,
    association_id: UUID,
) -> UserHouseholdAssociation:
    """``user_id`` is None for an unauthenticated user that owns nothing yet."""
    return require_user_household(
        None
        if user_id is None
        else read_owned_user_household_row(
            session,
            user_id=user_id,
            country_id=country_id,
            association_id=association_id,
        ),
        association_id=association_id,
    )


def resolve_user_household_reference(
    session: Session,
    *,
    country_id: str,
    household_id: UUID | None,
    legacy_household_id: int | None,
) -> UUID | None:
    """Validate an explicit v2 household and combine it with the v1 mapping."""
    if household_id is not None:
        validate_association_household(
            country_id=country_id,
            household_id=household_id,
            household=read_household_for_association(session, household_id),
        )
    mapped_household_id = (
        read_copied_household_ids(
            session,
            country_id=country_id,
            legacy_household_ids=(legacy_household_id,),
        ).get(legacy_household_id)
        if legacy_household_id is not None
        else None
    )
    return resolve_association_household_id(
        requested_household_id=household_id,
        mapped_household_id=mapped_household_id,
    )


def read_all_user_households(
    session: Session, *, user_id: UUID
) -> tuple[UserHouseholdRead, ...]:
    """Return every household association owned by a user, across countries."""
    return tuple(
        user_household_read(row)
        for row in read_all_user_household_rows(session, user_id=user_id)
    )


class V2UserHouseholdService:
    """Sequence owner-scoped association operations through explicit sessions."""

    def __init__(
        self,
        database_session: UserHouseholdDatabaseSession,
        legacy_references: LegacyReferenceChecker | None = None,
    ) -> None:
        """Open sessions through ``database_session`` and check v1 ids with the checker.

        Without ``legacy_references``, an operation that names a v1 household
        raises LegacyReferenceCheckUnavailableError.
        """
        self._database_session = database_session
        self._legacy_references = legacy_references

    def _require_legacy_household(
        self, *, country_id: str, legacy_household_id: int
    ) -> None:
        require_legacy_reference(
            self._legacy_references,
            LegacyRecordKind.HOUSEHOLD,
            country_id=country_id,
            legacy_id=legacy_household_id,
        )

    def create_user_household(
        self,
        *,
        principal: AccountPrincipal,
        association_input: UserHouseholdCreateFields,
    ) -> UserHouseholdRead:
        """Save a household for the principal, provisioning their v2 user if needed.

        A ``legacy_household_id`` must exist in v1 (LegacyReferenceNotFoundError)
        and links the v2 copy of that household when Stage 11 made one. An explicit
        ``household_id`` must exist in this country and match that copy
        (AssociationHouseholdNotFoundError, AssociationCountryConflictError or
        AssociationReferenceConflictError).
        """
        if association_input.legacy_household_id is not None:
            self._require_legacy_household(
                country_id=association_input.country_id,
                legacy_household_id=association_input.legacy_household_id,
            )
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session,
                principal,
                country_id=association_input.country_id,
            )
            household_id = resolve_user_household_reference(
                session,
                country_id=association_input.country_id,
                household_id=association_input.household_id,
                legacy_household_id=association_input.legacy_household_id,
            )
            return user_household_read(
                create_user_household(
                    session,
                    owned_user_household_input(
                        association_input,
                        user_id=owner.user_id,
                        household_id=household_id,
                    ),
                )
            )

    def get_user_household(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> UserHouseholdRead:
        """Return the principal's association in this country.

        Raise UserHouseholdNotFoundError when it is absent or another user's. A
        signed-out browser that has not saved anything yet owns nothing.
        """
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_for_read_in_session(
                session, principal, country_id=country_id
            )
            return user_household_read(
                read_owned_user_household(
                    session,
                    user_id=None if owner is None else owner.user_id,
                    country_id=country_id,
                    association_id=association_id,
                )
            )

    def list_user_households(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        household_filter: UserHouseholdFilter | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> UserHouseholdPage:
        """Return a page of the principal's associations in this country.

        ``household_filter`` narrows it to one household. A signed-out browser
        that has not saved anything yet gets an empty page.
        """
        selected = (
            household_filter if household_filter is not None else UserHouseholdFilter()
        )
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_for_read_in_session(
                session, principal, country_id=country_id
            )
            if owner is None:
                return user_household_page([], offset=offset, limit=limit)
            rows = read_user_household_rows(
                session,
                UserHouseholdListing(
                    country_id=country_id,
                    user_id=owner.user_id,
                    household_id=selected.household_id,
                    legacy_household_id=selected.legacy_household_id,
                    offset=offset,
                    limit=limit,
                ),
            )
            return user_household_page(rows, offset=offset, limit=limit)

    def patch_user_household(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
        association_input: UserHouseholdUpdateInput,
    ) -> UserHouseholdRead:
        """Update the supplied fields of the principal's association in this country.

        A new ``legacy_household_id`` must exist in v1 and repoints ``household_id``
        to the v2 copy of that household, or to None when there is no copy. Raise
        UserHouseholdNotFoundError when the association is not the principal's.
        """
        repoint = "legacy_household_id" in association_input.model_fields_set
        if repoint:
            if association_input.legacy_household_id is None:
                msg = "legacy_household_id must not be null"
                raise TypeError(msg)
            self._require_legacy_household(
                country_id=country_id,
                legacy_household_id=association_input.legacy_household_id,
            )
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            association = read_owned_user_household(
                session,
                user_id=owner.user_id,
                country_id=country_id,
                association_id=association_id,
            )
            repointed_household_id = (
                read_copied_household_ids(
                    session,
                    country_id=country_id,
                    legacy_household_ids=(association_input.legacy_household_id,),
                ).get(association_input.legacy_household_id)
                if repoint and association_input.legacy_household_id is not None
                else None
            )
            return user_household_read(
                update_user_household(
                    session,
                    association,
                    association_input,
                    repointed_household_id=repointed_household_id,
                    repoint=repoint,
                )
            )

    def delete_user_household(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> None:
        """Delete the principal's association, or raise UserHouseholdNotFoundError."""
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            delete_user_household(
                session,
                read_owned_user_household(
                    session,
                    user_id=owner.user_id,
                    country_id=country_id,
                    association_id=association_id,
                ),
            )
