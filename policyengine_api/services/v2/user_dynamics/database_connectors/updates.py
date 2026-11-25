"""Database updates used by the operations on users' saved dynamics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.data.v2.models.base import utc_now

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserDynamic
    from policyengine_api.services.v2.user_dynamics.types import (
        UserDynamicUpdateInput,
    )


def update_user_dynamic(
    session: Session,
    saved_dynamic: UserDynamic,
    update_input: UserDynamicUpdateInput,
) -> UserDynamic:
    """Apply the supplied fields, bump ``updated_at`` and return the row.

    The service checks a new ``dynamic_id`` before calling this.
    """
    for field_name, value in update_input.model_dump(exclude_unset=True).items():
        setattr(saved_dynamic, field_name, value)
    saved_dynamic.updated_at = utc_now()
    session.add(saved_dynamic)
    session.flush()
    session.refresh(saved_dynamic)
    return saved_dynamic
