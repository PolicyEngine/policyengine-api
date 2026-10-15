"""Pure representation transformations for v2 user-simulation operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_api.services.v2.user_simulations.types import (
    UserSimulationCreateFields,
    UserSimulationCreationInput,
    UserSimulationPage,
    UserSimulationRead,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.data.v2.models import UserSimulationAssociation


def user_simulation_read(
    association: UserSimulationAssociation,
) -> UserSimulationRead:
    """Convert a stored association row to the service's read model."""
    return UserSimulationRead(
        id=association.id,
        country_id=association.country_id,
        user_id=association.user_id,
        simulation_id=association.simulation_id,
        legacy_simulation_id=association.legacy_simulation_id,
        name=association.name,
        description=association.description,
        created_at=association.created_at,
        updated_at=association.updated_at,
    )


def user_simulation_page(
    rows: list[UserSimulationAssociation],
    *,
    offset: int,
    limit: int,
) -> UserSimulationPage:
    """Build a page from up to ``limit + 1`` rows.

    The extra row is not returned; it only sets ``has_more``.
    """
    return UserSimulationPage(
        items=tuple(user_simulation_read(row) for row in rows[:limit]),
        offset=offset,
        limit=limit,
        has_more=len(rows) > limit,
    )


def owned_user_simulation_input(
    fields: UserSimulationCreateFields,
    *,
    user_id: UUID,
) -> UserSimulationCreationInput:
    """Add the owner resolved from the session principal to the caller's fields."""
    return UserSimulationCreationInput(**fields.model_dump(), user_id=user_id)
