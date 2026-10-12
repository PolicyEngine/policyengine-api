"""Strict HTTP request models for signed-in v2 user-simulation associations."""

from policyengine_api.services.v2.user_simulations.types import (
    UserSimulationCreateFields,
    UserSimulationUpdateInput,
)


class UserSimulationCreateRequest(UserSimulationCreateFields):
    """Association fields; the owner is taken from the bearer token."""


class UserSimulationPatchRequest(UserSimulationUpdateInput):
    """Explicitly supplied mutable link or presentation fields."""
