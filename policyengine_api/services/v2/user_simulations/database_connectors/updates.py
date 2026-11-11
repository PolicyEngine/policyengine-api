"""Database updates for mutable v2 user-simulation association fields."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError

from policyengine_api.data.v2.models.base import utc_now
from policyengine_api.services.v2.associations.validators import violates_foreign_key
from policyengine_api.services.v2.user_simulations.validators import (
    SAVED_SIMULATION_FOREIGN_KEY,
    simulation_not_found,
)

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserSimulationAssociation
    from policyengine_api.services.v2.user_simulations.types import (
        UserSimulationUpdateInput,
    )


def update_user_simulation(
    session: Session,
    association: UserSimulationAssociation,
    association_input: UserSimulationUpdateInput,
) -> UserSimulationAssociation:
    """Apply only the supplied fields, bump ``updated_at`` and return the row.

    Raise AssociationSimulationNotFoundError when the simulation's foreign key
    refuses the row's new ``simulation_id``: the service checked the
    simulation in this transaction, so it was deleted after that check. The
    simulation and country are read before the flush, which expires the row
    when it fails.
    """
    for field_name, value in association_input.model_dump(exclude_unset=True).items():
        setattr(association, field_name, value)
    association.updated_at = utc_now()
    simulation_id = association.simulation_id
    country_id = association.country_id
    session.add(association)
    try:
        session.flush()
    except IntegrityError as error:
        if simulation_id is not None and violates_foreign_key(
            error, SAVED_SIMULATION_FOREIGN_KEY
        ):
            raise simulation_not_found(
                simulation_id=simulation_id, country_id=country_id
            ) from error
        raise
    session.refresh(association)
    return association
