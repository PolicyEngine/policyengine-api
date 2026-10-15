"""Database deletes for v2 user-simulation associations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlmodel import Session

    from policyengine_api.data.v2.models import UserSimulationAssociation


def delete_user_simulation(
    session: Session,
    association: UserSimulationAssociation,
) -> None:
    """Delete an association row; the simulation it names is not touched."""
    session.delete(association)
    session.flush()
