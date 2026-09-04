"""Strict HTTP request models for native v2 user-policy associations."""

from policyengine_api.services.v2.user_policies.types import (
    UserPolicyCreationInput,
    UserPolicyUpdateInput,
)


class UserPolicyCreateRequest(UserPolicyCreationInput):
    """Association identity, immutable link fields, and presentation fields."""


class UserPolicyPatchRequest(UserPolicyUpdateInput):
    """Explicitly supplied mutable presentation fields."""
