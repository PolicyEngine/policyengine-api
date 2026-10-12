"""Database inserts for v2 user-household associations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col

from policyengine_api.data.v2.models import UserHouseholdAssociation
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdCreationInput,
)


def create_user_household(
    session: Session,
    association_input: UserHouseholdCreationInput,
) -> UserHouseholdAssociation:
    association = UserHouseholdAssociation(**association_input.model_dump())
    session.add(association)
    session.flush()
    session.refresh(association)
    return association


def import_user_household(
    session: Session,
    association_input: UserHouseholdCreationInput,
) -> UUID | None:
    """Insert one imported association unless its client_ref already exists."""

    return session.execute(
        insert(UserHouseholdAssociation)
        .values(**association_input.model_dump())
        .on_conflict_do_nothing(
            constraint="uq_user_household_associations_user_client_ref"
        )
        .returning(col(UserHouseholdAssociation.id))
    ).scalar_one_or_none()
