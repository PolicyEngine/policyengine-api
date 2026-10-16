"""Proof fixture: a validator that loads records itself. The rule must reject it."""

from sqlmodel import Session, select

from policyengine_api.data.v2.models import Policy


def validate_policy_exists(session: Session, policy_id: int) -> Policy:
    """Load the policy and fail if it doesn't exist."""
    policy = session.exec(select(Policy).where(Policy.id == policy_id)).first()
    if policy is None:
        raise ValueError(policy_id)
    return policy
