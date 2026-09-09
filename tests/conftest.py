import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

# API startup now requires an explicit direct-gateway rollback target. Tests use
# the non-routable example hostname unless a case overrides it.
os.environ.setdefault(
    "OLD_SIMULATION_GATEWAY_URL",
    "https://old-simulation-gateway.example.test",
)

# Add the project root directory to PYTHONPATH
root_dir = Path(__file__).parent
sys.path.append(str(root_dir))
"""Shared fixtures"""


@pytest.fixture
def mock_v2_runtime_settings():
    """Avoid external v2 configuration access in ordinary API route tests."""

    with patch(
        "policyengine_api.data.v2.settings.load_v2_runtime_database_settings",
        return_value=object(),
    ):
        yield


@pytest.fixture
def api_client(mock_v2_runtime_settings):
    """Provide a Flask client without starting a Redis server."""
    from policyengine_api.api import app

    app.config["TESTING"] = True
    yield app.test_client()
