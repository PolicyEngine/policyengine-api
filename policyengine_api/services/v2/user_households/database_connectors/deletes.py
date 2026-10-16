"""Database deletes for v2 user-household associations."""

from sqlmodel import Session

from policyengine_api.data.v2.models import UserHouseholdAssociation


def delete_user_household(
    session: Session,
    association: UserHouseholdAssociation,
) -> None:
    """Delete an association row; the household it points to is kept."""
    session.delete(association)
    session.flush()
