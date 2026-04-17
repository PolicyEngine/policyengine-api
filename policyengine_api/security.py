"""Security helpers for sensitive API routes."""

import os
from functools import wraps

from flask import request
from werkzeug.exceptions import Unauthorized


def require_simulation_analysis_api_key(view):
    """Require a shared API key for simulation analysis requests."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        expected_key = os.getenv("POLICYENGINE_API_AI_ANALYSIS_API_KEY", "").strip()
        if not expected_key:
            raise Unauthorized("Simulation analysis API key is not configured")

        if request.headers.get("X-PolicyEngine-Api-Key") == expected_key:
            return view(*args, **kwargs)

        raise Unauthorized("API key required for simulation analysis")

    return wrapped
