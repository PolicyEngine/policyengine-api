"""Database updates for mutable v2 user-household association fields."""

from sqlmodel import Session

from policyengine_api.data.v2.models import UserHouseholdAssociation
from policyengine_api.data.v2.models.base import utc_now
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdUpdateInput,
)


def update_user_household(
    session: Session,
    association: UserHouseholdAssociation,
    association_input: UserHouseholdUpdateInput,
) -> UserHouseholdAssociation:
    for field_name, value in association_input.model_dump(exclude_unset=True).items():
        setattr(association, field_name, value)
    association.updated_at = utc_now()
    session.add(association)
    session.flush()
    session.refresh(association)
    return association
