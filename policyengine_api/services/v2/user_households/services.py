"""Application services for native v2 user-household associations.

The owner always comes from the verified session principal. v1 references are
checked in a short read-only v1 transaction before the v2 transaction opens.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlmodel import Session

from policyengine_api.data.v2.models import UserHouseholdAssociation
from policyengine_api.services.v2.associations.types import LegacyReferenceChecker
from policyengine_api.services.v2.associations.validators import (
    require_unused_client_ref,
)
from policyengine_api.services.v2.identity.services import (
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.identity.types import UserPrincipal
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordKind
from policyengine_api.services.v2.user_households.database_connectors.creates import (
    create_user_household,
    import_user_household,
)
from policyengine_api.services.v2.user_households.database_connectors.deletes import (
    delete_user_household,
)
from policyengine_api.services.v2.user_households.database_connectors.reads import (
    read_all_user_household_rows,
    read_copied_household_ids,
    read_household_for_association,
    read_owned_user_household_row,
    read_user_household_id_by_client_ref,
    read_user_household_rows,
)
from policyengine_api.services.v2.user_households.database_connectors.updates import (
    update_user_household,
)
from policyengine_api.services.v2.user_households.database_session import (
    UserHouseholdDatabaseSession,
)
from policyengine_api.services.v2.user_households.transformations import (
    imported_user_household_input,
    owned_user_household_input,
    user_household_page,
    user_household_read,
)
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdCreateFields,
    UserHouseholdImportItem,
    UserHouseholdPage,
    UserHouseholdRead,
    UserHouseholdUpdateInput,
)
from policyengine_api.services.v2.user_households.validators import (
    require_user_household,
    resolve_association_household_id,
    validate_association_household,
)


class UserHouseholdImportIntegrityError(RuntimeError):
    """Raised when an imported client_ref resolves to no stored association."""


def read_owned_user_household(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    association_id: UUID,
) -> UserHouseholdAssociation:
    return require_user_household(
        read_owned_user_household_row(
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


def import_user_households_in_session(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    items: Sequence[UserHouseholdImportItem],
) -> dict[str, UUID]:
    """Insert imported associations idempotently on ``(user_id, client_ref)``."""

    copied = read_copied_household_ids(
        session,
        country_id=country_id,
        legacy_household_ids={item.legacy_household_id for item in items},
    )
    imported: dict[str, UUID] = {}
    for item in items:
        association_id = import_user_household(
            session,
            imported_user_household_input(
                item,
                country_id=country_id,
                user_id=user_id,
                household_id=copied.get(item.legacy_household_id),
            ),
        ) or read_user_household_id_by_client_ref(
            session,
            user_id=user_id,
            client_ref=item.client_ref,
        )
        if association_id is None:
            raise UserHouseholdImportIntegrityError(
                "imported user-household client_ref did not resolve to a stored row"
            )
        imported[item.client_ref] = association_id
    return imported


class V2UserHouseholdService:
    """Sequence owner-scoped association operations through explicit sessions."""

    def __init__(
        self,
        database_session: UserHouseholdDatabaseSession,
        legacy_references: LegacyReferenceChecker | None = None,
    ) -> None:
        self._database_session = database_session
        self._legacy_references = legacy_references

    def _require_legacy_household(
        self, *, country_id: str, legacy_household_id: int
    ) -> None:
        if self._legacy_references is None:
            raise RuntimeError("v1 reference checks are not configured")
        self._legacy_references.require_existing(
            country_id=country_id,
            requested={LegacyRecordKind.HOUSEHOLD: (legacy_household_id,)},
        )

    def create_user_household(
        self,
        *,
        principal: UserPrincipal,
        association_input: UserHouseholdCreateFields,
    ) -> UserHouseholdRead:
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
            if association_input.client_ref is not None:
                require_unused_client_ref(
                    read_user_household_id_by_client_ref(
                        session,
                        user_id=owner.user_id,
                        client_ref=association_input.client_ref,
                    ),
                    client_ref=association_input.client_ref,
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
        principal: UserPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> UserHouseholdRead:
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            return user_household_read(
                read_owned_user_household(
                    session,
                    user_id=owner.user_id,
                    country_id=country_id,
                    association_id=association_id,
                )
            )

    def list_user_households(
        self,
        *,
        principal: UserPrincipal,
        country_id: str,
        household_id: UUID | None = None,
        legacy_household_id: int | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> UserHouseholdPage:
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            rows = read_user_household_rows(
                session,
                country_id=country_id,
                user_id=owner.user_id,
                household_id=household_id,
                legacy_household_id=legacy_household_id,
                offset=offset,
                limit=limit,
            )
            return user_household_page(rows, offset=offset, limit=limit)

    def patch_user_household(
        self,
        *,
        principal: UserPrincipal,
        country_id: str,
        association_id: UUID,
        association_input: UserHouseholdUpdateInput,
    ) -> UserHouseholdRead:
        repoint = "legacy_household_id" in association_input.model_fields_set
        if repoint:
            assert association_input.legacy_household_id is not None
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
        principal: UserPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> None:
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
