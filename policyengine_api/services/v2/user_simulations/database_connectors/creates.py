"""Database inserts for v2 user-simulation associations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError

from policyengine_api.data.v2.models import UserSimulationAssociation
from policyengine_api.services.v2.associations.validators import violates_foreign_key
from policyengine_api.services.v2.user_simulations.validators import (
    SAVED_SIMULATION_FOREIGN_KEY,
    simulation_not_found,
)

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.services.v2.user_simulations.types import (
        UserSimulationCreationInput,
    )


def create_user_simulation(
    session: Session,
    association_input: UserSimulationCreationInput,
) -> UserSimulationAssociation:
    """Insert an association and return it with its database-generated fields loaded.

    Raise AssociationSimulationNotFoundError when the simulation's foreign key
    refuses the insert: the service checked the simulation in this
    transaction, so it was deleted after that check. The error names the
    input's values, since a failed flush expires the rows the session holds.
    """
    association = UserSimulationAssociation(**association_input.model_dump())
    session.add(association)
    try:
        session.flush()
    except IntegrityError as error:
        simulation_id = association_input.simulation_id
        if simulation_id is not None and violates_foreign_key(
            error, SAVED_SIMULATION_FOREIGN_KEY
        ):
            raise simulation_not_found(
                simulation_id=simulation_id,
                country_id=association_input.country_id,
            ) from error
        raise
    session.refresh(association)
    return association
