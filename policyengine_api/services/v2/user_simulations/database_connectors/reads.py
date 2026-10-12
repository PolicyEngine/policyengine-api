"""Database reads for v2 user-simulation associations."""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import UserSimulationAssociation


def read_owned_user_simulation_row(
    session: Session,
    *,
    user_id: UUID,
    country_id: str,
    association_id: UUID,
) -> UserSimulationAssociation | None:
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


def read_user_simulation_id_by_client_ref(
    session: Session,
    *,
    user_id: UUID,
    client_ref: str,
) -> UUID | None:
    return session.exec(
        select(UserSimulationAssociation.id).where(
            UserSimulationAssociation.user_id == user_id,
            UserSimulationAssociation.client_ref == client_ref,
        )
    ).one_or_none()
