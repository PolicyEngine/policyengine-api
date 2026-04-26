import os
from unittest.mock import patch

import pytest

os.environ.setdefault("FLASK_DEBUG", "1")

from policyengine_api.api import app
from tests.to_refactor.fixtures.simulation_analysis_fixtures import test_json


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_simulation_analysis_rejects_requests_without_api_key(client, monkeypatch):
    monkeypatch.setenv("POLICYENGINE_API_AI_ANALYSIS_API_KEY", "secret-key")

    response = client.post(
        "/us/simulation-analysis",
        json=test_json,
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )

    assert response.status_code == 401
    assert "API key required" in response.json["message"]


def test_simulation_analysis_allows_requests_with_api_key(client, monkeypatch):
    monkeypatch.setenv("POLICYENGINE_API_AI_ANALYSIS_API_KEY", "secret-key")

    with patch(
        "policyengine_api.routes.simulation_analysis_routes.simulation_analysis_service.execute_analysis",
        return_value=("Existing analysis", "static"),
    ) as mock_execute_analysis:
        response = client.post(
            "/us/simulation-analysis",
            json=test_json,
            headers={"X-PolicyEngine-Api-Key": "secret-key"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert response.status_code == 200
    assert response.json["result"] == "Existing analysis"
    mock_execute_analysis.assert_called_once()
