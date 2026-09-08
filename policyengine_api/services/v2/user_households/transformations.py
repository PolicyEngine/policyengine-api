"""Pure representation transformations for v2 user-household operations."""

from policyengine_api.data.v2.models import UserHouseholdAssociation
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdPage,
    UserHouseholdRead,
)


def user_household_read(
    association: UserHouseholdAssociation,
) -> UserHouseholdRead:
    return UserHouseholdRead(
        id=association.id,
        country_id=association.country_id,
        user_id=association.user_id,
        household_id=association.household_id,
        name=association.name,
        description=association.description,
        created_at=association.created_at,
        updated_at=association.updated_at,
    )


def user_household_page(
    rows: list[UserHouseholdAssociation],
    *,
    offset: int,
    limit: int,
) -> UserHouseholdPage:
    return UserHouseholdPage(
        items=tuple(user_household_read(row) for row in rows[:limit]),
        offset=offset,
        limit=limit,
        has_more=len(rows) > limit,
    )
