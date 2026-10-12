"""Database inserts for v2 user-simulation associations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from policyengine_api.data.v2.models import UserSimulationAssociation
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


def import_user_simulation(
    session: Session,
    association_input: UserSimulationCreationInput,
) -> UUID | None:
    """Insert one imported association unless its client_ref already exists."""

    return session.execute(
        insert(UserSimulationAssociation)
        .values(**association_input.model_dump())
        .on_conflict_do_nothing(
            constraint="uq_user_simulation_associations_user_client_ref"
        )
        .returning(col(UserSimulationAssociation.id))
    ).scalar_one_or_none()
