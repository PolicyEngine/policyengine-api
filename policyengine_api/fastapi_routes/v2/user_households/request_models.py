"""Strict HTTP request models for v2 user-household associations."""

from policyengine_api.services.v2.user_households.types import (
    UserHouseholdCreateFields,
    UserHouseholdUpdateInput,
)


class UserHouseholdCreateRequest(UserHouseholdCreateFields):
    """Association fields; the owner is taken from the request credential."""


class UserHouseholdPatchRequest(UserHouseholdUpdateInput):
    """Explicitly supplied mutable link or presentation fields."""
