"""Security helpers for sensitive API routes."""

import os
from functools import wraps

from flask import request
from werkzeug.exceptions import Unauthorized

_LOCAL_CLIENT_HOSTS = {"127.0.0.1", "::1", "localhost"}


def require_simulation_analysis_api_key(view):
    """Require a shared API key for non-local simulation analysis requests."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        client_host = request.remote_addr
        if client_host in _LOCAL_CLIENT_HOSTS:
            return view(*args, **kwargs)

        expected_key = os.getenv(
            "POLICYENGINE_API_AI_ANALYSIS_API_KEY", ""
        ).strip()
        if expected_key and request.headers.get("X-PolicyEngine-Api-Key") == expected_key:
            return view(*args, **kwargs)

        raise Unauthorized("API key required for simulation analysis")

    return wrapped
