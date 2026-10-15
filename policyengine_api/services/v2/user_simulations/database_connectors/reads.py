"""Database reads for v2 user-simulation associations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import UserSimulationAssociation

if TYPE_CHECKING:
    from uuid import UUID


def read_owned_user_simulation_row(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    association_id: UUID,
) -> UserSimulationAssociation | None:
    """Return the user's association with this id in this country, or None."""
    return session.exec(
        select(UserSimulationAssociation).where(
            UserSimulationAssociation.id == association_id,
            UserSimulationAssociation.country_id == country_id,
            UserSimulationAssociation.user_id == user_id,
        )
    ).one_or_none()


def read_user_simulation_rows(
    session: Session,
    *,
    country_id: str,
    user_id: UUID,
    legacy_simulation_id: int | None,
    offset: int,
    limit: int,
) -> list[UserSimulationAssociation]:
    """Return up to ``limit + 1`` of a user's associations in creation order.

    With ``legacy_simulation_id``, only associations to that v1 simulation are
    returned. The extra row lets the caller report whether another page exists.
    """
    statement = select(UserSimulationAssociation).where(
        UserSimulationAssociation.country_id == country_id,
        UserSimulationAssociation.user_id == user_id,
    )
    if legacy_simulation_id is not None:
        statement = statement.where(
            UserSimulationAssociation.legacy_simulation_id == legacy_simulation_id
        )
    return list(
        session.exec(
            statement.order_by(
                col(UserSimulationAssociation.created_at),
                col(UserSimulationAssociation.id),
            )
            .offset(offset)
            .limit(limit + 1)
        ).all()
    )


def read_all_user_simulation_rows(
    session: Session, *, user_id: UUID
) -> list[UserSimulationAssociation]:
    """Return every association the user owns, in every country, in creation order."""
    return list(
        session.exec(
            select(UserSimulationAssociation)
            .where(UserSimulationAssociation.user_id == user_id)
            .order_by(
                col(UserSimulationAssociation.created_at),
                col(UserSimulationAssociation.id),
            )
        ).all()
    )
