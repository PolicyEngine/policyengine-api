"""Application services for native v2 user-simulation associations.

A saved simulation names a v2 simulation, a v1 simulation, or both. The owner
always comes from the verified session principal (a signed-in user or a
signed-out browser). Before the v2 transaction opens, a v1 reference is
checked in a short read-only v1 transaction, and a v2 simulation with the
simulation service, which owns v2 simulations. Reads never provision a browser's
unauthenticated user; one that does not exist yet owns no records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.associations.services import (
    require_legacy_reference,
)
from policyengine_api.services.v2.associations.transformations import (
    repointed_references,
)
from policyengine_api.services.v2.associations.types import RecordReferences
from policyengine_api.services.v2.associations.validators import (
    require_simulation_reference_checker,
    require_unchanged_references,
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
    stored_simulation_references,
    user_simulation_page,
    user_simulation_read,
)
from policyengine_api.services.v2.user_simulations.types import UserSimulationListing
from policyengine_api.services.v2.user_simulations.validators import (
    require_user_simulation,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserSimulationAssociation
    from policyengine_api.services.v2.associations.types import (
        LegacyReferenceChecker,
        SimulationReferenceChecker,
    )
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
    lock: bool = False,
) -> UserSimulationAssociation:
    """``user_id`` is None for an unauthenticated user that owns nothing yet.

    With ``lock``, the row stays locked until the session's transaction ends.
    """
    return require_user_simulation(
        None
        if user_id is None
        else read_owned_user_simulation_row(
            session,
            user_id=user_id,
            country_id=country_id,
            association_id=association_id,
            lock=lock,
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
        simulation_references: SimulationReferenceChecker | None = None,
    ) -> None:
        """Open sessions through ``database_session``.

        ``legacy_references`` checks v1 simulations and
        ``simulation_references`` v2 simulations before a write. Saving or
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
        references: RecordReferences,
        check_legacy_simulation: bool,
    ) -> None:
        """Check a saved simulation's references before the v2 transaction opens.

        The v1 simulation is checked when ``check_legacy_simulation`` is set.
        The v2 simulation is checked whenever there is one, and when there are
        both, it must be the simulation migrated from that v1 simulation.
        """
        if check_legacy_simulation and references.legacy_id is not None:
            require_legacy_reference(
                self._legacy_references,
                LegacyRecordKind.SIMULATION,
                country_id=country_id,
                legacy_id=references.legacy_id,
            )
        if references.v2_id is not None:
            require_simulation_reference_checker(
                self._simulation_references
            ).require_simulation(
                country_id=country_id,
                simulation_id=references.v2_id,
                legacy_simulation_id=references.legacy_id,
            )

    def _stored_references(
        self, *, principal: AccountPrincipal, country_id: str, association_id: UUID
    ) -> RecordReferences:
        """Read the references the principal's saved simulation holds now."""
        with self._database_session.read() as session:
            owner = resolve_principal_user_for_read_in_session(
                session, principal, country_id=country_id
            )
            return stored_simulation_references(
                read_owned_user_simulation(
                    session,
                    user_id=None if owner is None else owner.user_id,
                    country_id=country_id,
                    association_id=association_id,
                )
            )

    def create_user_simulation(
        self,
        *,
        principal: AccountPrincipal,
        association_input: UserSimulationCreateFields,
    ) -> UserSimulationRead:
        """Save a simulation for the principal, provisioning its v2 user if needed.

        Each supplied reference is checked first: a v1 simulation in a
        read-only v1 transaction (LegacyReferenceNotFoundError), and a v2
        simulation with the simulation service
        (SimulationReferenceNotFoundError), each in the country.
        """
        self._require_references(
            country_id=association_input.country_id,
            references=RecordReferences(
                v2_id=association_input.simulation_id,
                legacy_id=association_input.legacy_simulation_id,
            ),
            check_legacy_simulation=True,
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
        """Return the principal's association, or raise UserSimulationNotFoundError.

        The association must be in this country. A signed-out browser that has
        never saved anything owns nothing, and is not provisioned by the read.
        """
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
        """Return a page of the principal's associations in this country.

        With ``legacy_simulation_id``, only saves of that v1 simulation are
        listed. A signed-out browser that has never saved anything gets an empty
        page and is not provisioned.
        """
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_for_read_in_session(
                session, principal, country_id=country_id
            )
            if owner is None:
                return user_simulation_page([], offset=offset, limit=limit)
            rows = read_user_simulation_rows(
                session,
                UserSimulationListing(
                    country_id=country_id,
                    user_id=owner.user_id,
                    legacy_simulation_id=legacy_simulation_id,
                    offset=offset,
                    limit=limit,
                ),
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
        """Update the supplied fields of one of the principal's associations.

        A new ``simulation_id`` or ``legacy_simulation_id`` is checked first,
        as on create, together with the reference the saved simulation keeps:
        when it will hold both, the v2 simulation must be the one migrated from
        that v1 simulation (AssociationReferenceConflictError). If the saved
        simulation changes during that check, AssociationConflictError is
        raised. Raise UserSimulationNotFoundError if the principal has no such
        association in this country.
        """
        checked: RecordReferences | None = None
        if (
            association_input.simulation_id is not None
            or association_input.legacy_simulation_id is not None
        ):
            stored = self._stored_references(
                principal=principal,
                country_id=country_id,
                association_id=association_id,
            )
            self._require_references(
                country_id=country_id,
                references=repointed_references(
                    stored,
                    v2_id=association_input.simulation_id,
                    legacy_id=association_input.legacy_simulation_id,
                ),
                check_legacy_simulation=(
                    association_input.legacy_simulation_id is not None
                ),
            )
            checked = stored
        with self._database_session.transaction() as session:
            owner = resolve_principal_user_in_session(
                session, principal, country_id=country_id
            )
            association = read_owned_user_simulation(
                session,
                user_id=owner.user_id,
                country_id=country_id,
                association_id=association_id,
                lock=checked is not None,
            )
            if checked is not None:
                require_unchanged_references(
                    stored_simulation_references(association),
                    checked=checked,
                    association_id=association_id,
                )
            return user_simulation_read(
                update_user_simulation(session, association, association_input)
            )

    def delete_user_simulation(
        self,
        *,
        principal: AccountPrincipal,
        country_id: str,
        association_id: UUID,
    ) -> None:
        """Delete one of the principal's associations in this country.

        Raise UserSimulationNotFoundError if the principal has no such association.
        """
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
