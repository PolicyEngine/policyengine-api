"""Proof fixture: a validator that checks an already-loaded record. The rule must accept it."""

from policyengine_api.data.v2.models import Policy


def validate_policy_exists(policy: Policy | None, policy_id: int) -> Policy:
    if policy is None:
        raise ValueError(policy_id)
    return policy
