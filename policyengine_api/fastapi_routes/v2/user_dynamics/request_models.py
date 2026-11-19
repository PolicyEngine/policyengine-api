"""Strict HTTP request models for users' saved dynamics."""

from policyengine_api.services.v2.user_dynamics.types import (
    UserDynamicCreateFields,
    UserDynamicUpdateInput,
)


class UserDynamicCreateRequest(UserDynamicCreateFields):
    """Saved-dynamic fields; the owner is taken from the request credential."""


class UserDynamicPatchRequest(UserDynamicUpdateInput):
    """Explicitly supplied fields to rename or repoint a saved dynamic."""
