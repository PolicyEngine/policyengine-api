"""Pure representation transformations for v2 user-household operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.user_households.types import (
    UserHouseholdCreateFields,
    UserHouseholdCreationInput,
    UserHouseholdPage,
    UserHouseholdRead,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.data.v2.models import UserHouseholdAssociation


def user_household_read(
    association: UserHouseholdAssociation,
) -> UserHouseholdRead:
    return UserHouseholdRead(
        id=association.id,
        country_id=association.country_id,
        user_id=association.user_id,
        household_id=association.household_id,
        legacy_household_id=association.legacy_household_id,
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


def owned_user_household_input(
    fields: UserHouseholdCreateFields,
    *,
    user_id: UUID,
    household_id: UUID | None,
) -> UserHouseholdCreationInput:
    return UserHouseholdCreationInput(
        **fields.model_dump(exclude={"household_id"}),
        user_id=user_id,
        household_id=household_id,
    )
