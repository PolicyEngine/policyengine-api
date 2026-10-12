"""Application services for native v2 user-simulation associations.

Stage 12A anchors saved simulations on v1 simulation IDs. The owner always
comes from the verified session principal, and v1 references are checked in a
short read-only v1 transaction before the v2 transaction opens.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlmodel import Session

from policyengine_api.data.v2.models import UserSimulationAssociation
from policyengine_api.services.v2.associations.types import LegacyReferenceChecker
from policyengine_api.services.v2.associations.validators import (
    require_unused_client_ref,
)
from policyengine_api.services.v2.identity.services import (
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.identity.types import UserPrincipal
from policyengine_api.services.v2.legacy_refs.types import LegacyRecordKind
from policyengine_api.services.v2.user_simulations.database_connectors.creates import (
    create_user_simulation,
    import_user_simulation,
)
from policyengine_api.services.v2.user_simulations.database_connectors.deletes import (
    delete_user_simulation,
)
from policyengine_api.services.v2.user_simulations.database_connectors.reads import (
    read_all_user_simulation_rows,
    read_owned_user_simulation_row,
    read_user_simulation_id_by_client_ref,
    read_user_simulation_rows,
)
from policyengine_api.services.v2.user_simulations.database_connectors.updates import (
    update_user_simulation,
)
from policyengine_api.services.v2.user_simulations.database_session import (
    UserSimulationDatabaseSession,
)
from policyengine_api.services.v2.user_simulations.transformations import (
    imported_user_simulation_input,
    owned_user_simulation_input,
    user_simulation_page,
    user_simulation_read,
)
from policyengine_api.services.v2.user_simulations.types import (
    UserSimulationCreateFields,
    UserSimulationImportItem,
    UserSimulationPage,
    UserSimulationRead,
    UserSimulationUpdateInput,
)
from policyengine_api.services.v2.user_simulations.validators import (
    require_imported_user_simulation,
    require_user_simulation,
)


def read_owned_user_simulation(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    association_id: UUID,
) -> UserSimulationAssociation:
    return require_user_simulation(
        read_owned_user_simulation_row(
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


def import_user_simulations_in_session(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    items: Sequence[UserSimulationImportItem],
) -> dict[str, UUID]:
    """Insert imported associations idempotently on ``(user_id, client_ref)``."""

    imported: dict[str, UUID] = {}
    for item in items:
        imported[item.client_ref] = require_imported_user_simulation(
            import_user_simulation(
                session,
                imported_user_simulation_input(
                    item,
                    country_id=country_id,
                    user_id=user_id,
                ),
            )
            or read_user_simulation_id_by_client_ref(
                session,
                user_id=user_id,
                client_ref=item.client_ref,
            )
        )
    return imported


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
        if self._legacy_references is None:
            raise RuntimeError("v1 reference checks are not configured")
        self._legacy_references.require_existing(
            country_id=country_id,
            requested={LegacyRecordKind.SIMULATION: (legacy_simulation_id,)},
        )

    def create_user_simulation(
        self,
        *,
        principal: UserPrincipal,
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
            if association_input.client_ref is not None:
                require_unused_client_ref(
                    read_user_simulation_id_by_client_ref(
                        session,
                        user_id=owner.user_id,
                        client_ref=association_input.client_ref,
                    ),
                    client_ref=association_input.client_ref,
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
        principal: UserPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> UserSimulationRead:
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            return user_simulation_read(
                read_owned_user_simulation(
                    session,
                    user_id=owner.user_id,
                    country_id=country_id,
                    association_id=association_id,
                )
            )

    def list_user_simulations(
        self,
        *,
        principal: UserPrincipal,
        country_id: str,
        legacy_simulation_id: int | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> UserSimulationPage:
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
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
        principal: UserPrincipal,
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
        principal: UserPrincipal,
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
