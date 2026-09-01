"""Strict HTTP request models for native v2 user-policy associations."""

from policyengine_api.services.v2.user_policies.commands import (
    UserPolicyCreateCommand,
    UserPolicyPatchCommand,
)


class UserPolicyCreateRequest(UserPolicyCreateCommand):
    """Association identity, immutable link fields, and presentation fields."""


class UserPolicyPatchRequest(UserPolicyPatchCommand):
    """Explicitly supplied mutable presentation fields."""
