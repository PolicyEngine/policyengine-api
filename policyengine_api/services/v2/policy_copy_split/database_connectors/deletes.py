"""Database deletes used by the policy copy split."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import delete
from sqlmodel import col

from policyengine_api.data.v2.models import Policy

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session


def delete_policy(session: Session, policy_id: UUID) -> None:
    """Delete a policy that nothing names; its values go with it.

    ``parameter_values.policy_id`` cascades, and every other foreign key to
    ``policies`` either refuses the delete or sets its column to null, so the
    service checks first that nothing else names it.
    """
    session.execute(delete(Policy).where(col(Policy.id) == policy_id))
