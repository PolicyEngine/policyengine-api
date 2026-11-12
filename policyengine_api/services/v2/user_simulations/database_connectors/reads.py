"""Database reads for v2 user-simulation associations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import (
    Simulation,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    UserSimulationAssociation,
)

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.user_simulations.types import (
        UserSimulationListing,
    )


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
    listing: UserSimulationListing,
) -> list[UserSimulationAssociation]:
    """Return up to ``limit + 1`` of a user's associations in creation order.

    With the listing's ``legacy_simulation_id``, only associations to that v1
    simulation are returned. The extra row lets the caller report whether
    another page exists.
    """
    statement = select(UserSimulationAssociation).where(
        UserSimulationAssociation.country_id == listing.country_id,
        UserSimulationAssociation.user_id == listing.user_id,
    )
    if listing.legacy_simulation_id is not None:
        statement = statement.where(
            UserSimulationAssociation.legacy_simulation_id
            == listing.legacy_simulation_id
        )
    return list(
        session.exec(
            statement.order_by(
                col(UserSimulationAssociation.created_at),
                col(UserSimulationAssociation.id),
            )
            .offset(listing.offset)
            .limit(listing.limit + 1)
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


def read_simulation_exists(
    session: Session, *, country_id: str, simulation_id: UUID
) -> bool:
    """Return whether a detailed-save simulation of the country's model has this id.

    A simulation has no country column: its catalog version's model is the
    country's (``policyengine-<country>``).
    """
    return (
        session.exec(
            select(Simulation.id)
            .join(
                TaxBenefitModelVersion,
                col(TaxBenefitModelVersion.id)
                == Simulation.tax_benefit_model_version_id,
            )
            .join(
                TaxBenefitModel,
                col(TaxBenefitModel.id) == TaxBenefitModelVersion.model_id,
            )
            .where(
                Simulation.id == simulation_id,
                TaxBenefitModel.name == f"policyengine-{country_id}",
            )
        ).one_or_none()
        is not None
    )
