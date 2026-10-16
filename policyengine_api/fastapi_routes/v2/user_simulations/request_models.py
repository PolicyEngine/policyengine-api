"""Strict HTTP request models for v2 user-simulation associations."""

from policyengine_api.services.v2.user_simulations.types import (
    UserSimulationCreateFields,
    UserSimulationUpdateInput,
)


class UserSimulationCreateRequest(UserSimulationCreateFields):
    """Association fields; the owner is taken from the request credential."""


class UserSimulationPatchRequest(UserSimulationUpdateInput):
    """Explicitly supplied mutable link or presentation fields."""
