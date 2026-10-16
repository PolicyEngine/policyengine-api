"""Strict HTTP request models for v2 user-policy associations."""

from policyengine_api.services.v2.user_policies.types import (
    UserPolicyCreateFields,
    UserPolicyUpdateInput,
)


class UserPolicyCreateRequest(UserPolicyCreateFields):
    """Association fields; the owner is taken from the request credential."""


class UserPolicyPatchRequest(UserPolicyUpdateInput):
    """Explicitly supplied mutable link or presentation fields."""
