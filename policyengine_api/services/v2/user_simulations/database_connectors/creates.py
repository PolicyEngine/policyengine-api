"""Database inserts for v2 user-simulation associations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models import UserSimulationAssociation

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.services.v2.user_simulations.types import (
        UserSimulationCreationInput,
    )


def create_user_simulation(
    session: Session,
    association_input: UserSimulationCreationInput,
) -> UserSimulationAssociation:
    association = UserSimulationAssociation(**association_input.model_dump())
    session.add(association)
    session.flush()
    session.refresh(association)
    return association
