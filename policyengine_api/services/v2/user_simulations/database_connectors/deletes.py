"""Database deletes for v2 user-simulation associations."""

from __future__ import annotations

from sqlmodel import Session

from policyengine_api.data.v2.models import UserSimulationAssociation


def delete_user_simulation(
    session: Session,
    association: UserSimulationAssociation,
) -> None:
    session.delete(association)
    session.flush()
