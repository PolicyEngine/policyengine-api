"""Application services for native v2 user-simulation associations.

Stage 12A anchors saved simulations on v1 simulation IDs. The owner always
comes from the verified session principal (a signed-in user or a signed-out
browser), and v1 references are checked in a short read-only v1 transaction
before the v2 transaction opens. Reads never provision a browser's
unauthenticated user; one that does not exist yet owns no records.
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
from policyengine_api.services.v2.user_simulations.database_connectors.creates import (
    create_user_simulation,
)
from policyengine_api.services.v2.user_simulations.database_connectors.deletes import (
    delete_user_simulation,
)
from policyengine_api.services.v2.user_simulations.database_connectors.reads import (
    read_all_user_simulation_rows,
    read_owned_user_simulation_row,
    read_user_simulation_rows,
)
from policyengine_api.services.v2.user_simulations.database_connectors.updates import (
    update_user_simulation,
)
from policyengine_api.services.v2.user_simulations.transformations import (
    owned_user_simulation_input,
    user_simulation_page,
    user_simulation_read,
)
from policyengine_api.services.v2.user_simulations.validators import (
    require_user_simulation,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserSimulationAssociation
    from policyengine_api.services.v2.associations.types import LegacyReferenceChecker
    from policyengine_api.services.v2.identity.types import AccountPrincipal
    from policyengine_api.services.v2.user_simulations.database_session import (
        UserSimulationDatabaseSession,
    )
    from policyengine_api.services.v2.user_simulations.types import (
        UserSimulationCreateFields,
        UserSimulationPage,
        UserSimulationRead,
        UserSimulationUpdateInput,
    )


def read_owned_user_simulation(
    session: Session,
    *,
    user_id: UUID | None,
    country_id: str,
    association_id: UUID,
) -> UserSimulationAssociation:
    """``user_id`` is None for an unauthenticated user that owns nothing yet."""

    return require_user_simulation(
        None
        if user_id is None
        else read_owned_user_simulation_row(
            session,
            user_id=user_id,
            country_id=country_id,
            association_id=association_id,
        ),
        association_id=association_id,
    )


def read_all_user_simulations(
    session: Session, *, user_id: UUID
) -> tuple[UserSimulationRead, ...]:
    """Return every simulation association owned by a user, across countries."""

    return tuple(
        user_simulation_read(row)
        for row in read_all_user_simulation_rows(session, user_id=user_id)
    )


class V2UserSimulationService:
    """Sequence owner-scoped association operations through explicit sessions."""

    def __init__(
        self,
        database_session: UserSimulationDatabaseSession,
        legacy_references: LegacyReferenceChecker | None = None,
    ) -> None:
        self._database_session = database_session
        self._legacy_references = legacy_references

    def _require_legacy_simulation(
        self, *, country_id: str, legacy_simulation_id: int
    ) -> None:
        require_legacy_reference(
            self._legacy_references,
            LegacyRecordKind.SIMULATION,
            country_id=country_id,
            legacy_id=legacy_simulation_id,
        )

    def create_user_simulation(
        self,
        *,
        principal: AccountPrincipal,
        association_input: UserSimulationCreateFields,
    ) -> UserSimulationRead:
        self._require_legacy_simulation(
            country_id=association_input.country_id,
            legacy_simulation_id=association_input.legacy_simulation_id,
        )
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session,
                principal,
                country_id=association_input.country_id,
            )
            return user_simulation_read(
                create_user_simulation(
                    session,
                    owned_user_simulation_input(
                        association_input,
                        user_id=owner.user_id,
                    ),
                )
            )

    def get_user_simulation(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> UserSimulationRead:
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_for_read_in_session(
                session, principal, country_id=country_id
            )
            return user_simulation_read(
                read_owned_user_simulation(
                    session,
                    user_id=None if owner is None else owner.user_id,
                    country_id=country_id,
                    association_id=association_id,
                )
            )

    def list_user_simulations(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        legacy_simulation_id: int | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> UserSimulationPage:
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_for_read_in_session(
                session, principal, country_id=country_id
            )
            if owner is None:
                return user_simulation_page([], offset=offset, limit=limit)
            rows = read_user_simulation_rows(
                session,
                country_id=country_id,
                user_id=owner.user_id,
                legacy_simulation_id=legacy_simulation_id,
                offset=offset,
                limit=limit,
            )
            return user_simulation_page(rows, offset=offset, limit=limit)

    def patch_user_simulation(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
        association_input: UserSimulationUpdateInput,
    ) -> UserSimulationRead:
        if association_input.legacy_simulation_id is not None:
            self._require_legacy_simulation(
                country_id=country_id,
                legacy_simulation_id=association_input.legacy_simulation_id,
            )
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            return user_simulation_read(
                update_user_simulation(
                    session,
                    read_owned_user_simulation(
                        session,
                        user_id=owner.user_id,
                        country_id=country_id,
                        association_id=association_id,
                    ),
                    association_input,
                )
            )

    def delete_user_simulation(
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
            delete_user_simulation(
                session,
                read_owned_user_simulation(
                    session,
                    user_id=owner.user_id,
                    country_id=country_id,
                    association_id=association_id,
                ),
            )
