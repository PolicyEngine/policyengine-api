import os
from unittest.mock import patch

import pytest

os.environ.setdefault("FLASK_DEBUG", "1")

from policyengine_api.api import app
from tests.fixtures.simulation_analysis_prompt_fixtures import valid_input_us


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_ai_prompt_rejects_requests_without_api_key(client, monkeypatch):
    monkeypatch.setenv("POLICYENGINE_API_AI_ANALYSIS_API_KEY", "secret-key")

    response = client.post(
        "/us/ai-prompts/simulation_analysis",
        json=valid_input_us,
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )

    assert response.status_code == 401
    assert "API key required" in response.json["message"]


def test_ai_prompt_allows_requests_with_api_key(client, monkeypatch):
    monkeypatch.setenv("POLICYENGINE_API_AI_ANALYSIS_API_KEY", "secret-key")

    with patch(
        "policyengine_api.routes.ai_prompt_routes.ai_prompt_service.get_prompt",
        return_value="Prompt text",
    ) as mock_get_prompt:
        response = client.post(
            "/us/ai-prompts/simulation_analysis",
            json=valid_input_us,
            headers={"X-PolicyEngine-Api-Key": "secret-key"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert response.status_code == 200
    assert response.json["result"] == "Prompt text"
    mock_get_prompt.assert_called_once()


def test_tracer_analysis_rejects_requests_without_api_key(client, monkeypatch):
    monkeypatch.setenv("POLICYENGINE_API_AI_ANALYSIS_API_KEY", "secret-key")

    response = client.post(
        "/us/tracer-analysis",
        json={
            "household_id": 1500,
            "policy_id": 2,
            "variable": "disposable_income",
        },
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )

    assert response.status_code == 401
    assert "API key required" in response.json["message"]


def test_tracer_analysis_allows_requests_with_api_key(client, monkeypatch):
    monkeypatch.setenv("POLICYENGINE_API_AI_ANALYSIS_API_KEY", "secret-key")

    with patch(
        "policyengine_api.routes.tracer_analysis_routes.tracer_analysis_service.execute_analysis",
        return_value=("Existing analysis", "static"),
    ) as mock_execute_analysis:
        response = client.post(
            "/us/tracer-analysis",
            json={
                "household_id": 1500,
                "policy_id": 2,
                "variable": "disposable_income",
            },
            headers={"X-PolicyEngine-Api-Key": "secret-key"},
            environ_base={"REMOTE_ADDR": "203.0.113.10"},
        )

    assert response.status_code == 200
    assert response.json["result"] == "Existing analysis"
    mock_execute_analysis.assert_called_once_with(
        "us", 1500, 2, "disposable_income"
    )
