"""Strict HTTP request models for the native v2 policy API."""

from policyengine_api.services.v2.policies.commands import PolicyCreateCommand


MAXIMUM_POLICY_REQUEST_BYTES = 1_048_576


class PolicyCreateRequest(PolicyCreateCommand):
    """Native body containing immutable policy content only."""
