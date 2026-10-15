"""Database updates for mutable v2 user-simulation association fields."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models.base import utc_now

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
    for field_name, value in association_input.model_dump(exclude_unset=True).items():
        setattr(association, field_name, value)
    association.updated_at = utc_now()
    session.add(association)
    session.flush()
    session.refresh(association)
    return association
