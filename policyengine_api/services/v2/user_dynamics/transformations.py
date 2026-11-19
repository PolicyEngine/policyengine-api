"""Pure representation transformations for users' saved dynamics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.user_dynamics.types import (
    UserDynamicCreateFields,
    UserDynamicCreationInput,
    UserDynamicPage,
    UserDynamicRead,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.data.v2.models import UserDynamic


def user_dynamic_read(saved_dynamic: UserDynamic) -> UserDynamicRead:
    """Convert a stored saved-dynamic row to the service's read model."""
    return UserDynamicRead(
        id=saved_dynamic.id,
        country_id=saved_dynamic.country_id,
        user_id=saved_dynamic.user_id,
        dynamic_id=saved_dynamic.dynamic_id,
        name=saved_dynamic.name,
        description=saved_dynamic.description,
        created_at=saved_dynamic.created_at,
        updated_at=saved_dynamic.updated_at,
    )


def user_dynamic_page(
    rows: list[UserDynamic], *, offset: int, limit: int
) -> UserDynamicPage:
    """Build a page from up to ``limit + 1`` rows.

    The extra row is not returned; it only sets ``has_more``.
    """
    return UserDynamicPage(
        items=tuple(user_dynamic_read(row) for row in rows[:limit]),
        offset=offset,
        limit=limit,
        has_more=len(rows) > limit,
    )


def owned_user_dynamic_input(
    fields: UserDynamicCreateFields, *, user_id: UUID
) -> UserDynamicCreationInput:
    """Attach the session owner to the caller's saved-dynamic fields."""
    return UserDynamicCreationInput(**fields.model_dump(), user_id=user_id)
