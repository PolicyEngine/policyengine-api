"""Strict HTTP request models for the native v2 policy API."""

from policyengine_api.services.v2.policies.types import PolicyCreationInput


MAXIMUM_POLICY_REQUEST_BYTES = 1_048_576


class PolicyCreateRequest(PolicyCreationInput):
    """Native body containing immutable policy content only."""
