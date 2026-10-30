"""Database updates for mutable v2 user-household association fields."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models.base import utc_now
from policyengine_api.services.v2.user_households.types import (
    USER_HOUSEHOLD_REFERENCE_FIELDS,
)

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserHouseholdAssociation
    from policyengine_api.services.v2.user_households.types import (
        UserHouseholdReferences,
        UserHouseholdUpdateInput,
    )


def update_user_household(
    session: Session,
    association: UserHouseholdAssociation,
    association_input: UserHouseholdUpdateInput,
    *,
    references: UserHouseholdReferences | None = None,
) -> UserHouseholdAssociation:
    """Apply the supplied presentation fields, bump ``updated_at`` and return the row.

    With ``references``, also store both of its household references; the
    service resolves them, so the request's own reference fields are never copied.
    """
    for field_name, value in association_input.model_dump(
        exclude_unset=True, exclude=set(USER_HOUSEHOLD_REFERENCE_FIELDS)
    ).items():
        setattr(association, field_name, value)
    if references is not None:
        association.household_id = references.household_id
        association.legacy_household_id = references.legacy_household_id
    association.updated_at = utc_now()
    session.add(association)
    session.flush()
    session.refresh(association)
    return association
