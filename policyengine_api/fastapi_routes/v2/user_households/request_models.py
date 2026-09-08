"""Strict HTTP request models for native v2 user-household associations."""

from policyengine_api.services.v2.user_households.types import (
    UserHouseholdCreationInput,
    UserHouseholdUpdateInput,
)


class UserHouseholdCreateRequest(UserHouseholdCreationInput):
    """Association identity, immutable link fields, and presentation fields."""


class UserHouseholdPatchRequest(UserHouseholdUpdateInput):
    """Explicitly supplied mutable link or presentation fields."""
