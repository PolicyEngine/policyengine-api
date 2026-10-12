"""Pure representation transformations for v2 user-simulation operations."""

from __future__ import annotations

from uuid import UUID

from policyengine_api.data.v2.models import UserSimulationAssociation
from policyengine_api.services.v2.user_simulations.types import (
    UserSimulationCreateFields,
    UserSimulationCreationInput,
    UserSimulationImportItem,
    UserSimulationPage,
    UserSimulationRead,
)


def user_simulation_read(
    association: UserSimulationAssociation,
) -> UserSimulationRead:
    return UserSimulationRead(
        id=association.id,
        country_id=association.country_id,
        user_id=association.user_id,
        simulation_id=association.simulation_id,
        legacy_simulation_id=association.legacy_simulation_id,
        name=association.name,
        description=association.description,
        client_ref=association.client_ref,
        created_at=association.created_at,
        updated_at=association.updated_at,
    )


def user_simulation_page(
    rows: list[UserSimulationAssociation],
    *,
    offset: int,
    limit: int,
) -> UserSimulationPage:
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
    return UserSimulationCreationInput(**fields.model_dump(), user_id=user_id)


def imported_user_simulation_input(
    item: UserSimulationImportItem,
    *,
    country_id: str,
    user_id: UUID,
) -> UserSimulationCreationInput:
    return UserSimulationCreationInput.model_validate(
        {
            **item.model_dump(),
            "country_id": country_id,
            "user_id": user_id,
        }
    )
