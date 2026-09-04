import os
from pathlib import Path
import sys

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


@pytest.fixture(scope="session")
def api_client():
    """Provide a Flask client without starting a Redis server."""
    from policyengine_api.api import app

    app.config["TESTING"] = True
    yield app.test_client()
