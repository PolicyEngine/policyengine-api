"""Strict HTTP request models for the native v2 dynamic API."""

from policyengine_api.services.v2.dynamics.types import DynamicCreationInput

MAXIMUM_DYNAMIC_REQUEST_BYTES = 1_048_576


class DynamicCreateRequest(DynamicCreationInput):
    """Native body containing immutable dynamic content only.

    A dynamic holds the model's assumptions: parameters under
    ``gov.simulation``, and in the US also ``simulation``. Any other
    parameter belongs in a policy (``POST /v2/policies``).
    """
