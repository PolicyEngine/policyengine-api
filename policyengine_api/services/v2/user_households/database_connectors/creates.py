"""Database inserts for v2 user-household associations."""

from sqlmodel import Session

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
