import pytest
from unittest.mock import patch
from flask import Flask

from policyengine_api.services.simulation_analysis_service import (
    SimulationAnalysisService,
)
from policyengine_api.routes.simulation_analysis_routes import (
    execute_simulation_analysis,
)

from tests.fixtures.simulation_analysis_fixtures import test_json, test_impact

test_service = SimulationAnalysisService()


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


def test_execute_simulation_analysis_existing_analysis(app, rest_client):

    with app.test_request_context(json=test_json):
        with patch(
            "policyengine_api.services.ai_analysis_service.AIAnalysisService.get_existing_analysis"
        ) as mock_get_existing:
            mock_get_existing.return_value = (s for s in ["Existing analysis"])

            response = execute_simulation_analysis("us")

            assert response.status_code == 200
            assert b"Existing analysis" in response.data


def test_execute_simulation_analysis_new_analysis(app, rest_client):
    with app.test_request_context(json=test_json):
        with patch(
            "policyengine_api.services.ai_analysis_service.AIAnalysisService.get_existing_analysis"
        ) as mock_get_existing:
            mock_get_existing.return_value = None
            with patch(
                "policyengine_api.services.simulation_analysis_service.AIAnalysisService.trigger_ai_analysis"
            ) as mock_trigger:
                mock_trigger.return_value = (s for s in ["New analysis"])

                response = execute_simulation_analysis("us")

                assert response.status_code == 200
                assert b"New analysis" in response.data


def test_execute_simulation_analysis_error(app, rest_client):
    with app.test_request_context(json=test_json):
        with patch(
            "policyengine_api.services.ai_analysis_service.AIAnalysisService.get_existing_analysis"
        ) as mock_get_existing:
            mock_get_existing.return_value = None
            with patch(
                "policyengine_api.services.ai_analysis_service.AIAnalysisService.trigger_ai_analysis"
            ) as mock_trigger:
                mock_trigger.side_effect = Exception("Test error")

                response = execute_simulation_analysis("us")

                assert response.status_code == 500


def test_execute_simulation_analysis_enhanced_cps(app, rest_client):
    policy_details = dict(policy_json="policy details")

    test_json_enhanced_us = {
        "currency": "USD",
        "selected_version": "2023",
        "time_period": "2023",
        "impact": test_impact,
        "policy_label": "Test Policy",
        "policy": policy_details,
        "region": "enhanced_us",
        "relevant_parameters": ["param1", "param2"],
        "relevant_parameter_baseline_values": [
            {"param1": 100},
            {"param2": 200},
        ],
        "audience": "Normal",
    }
    with app.test_request_context(json=test_json_enhanced_us):
        with patch(
            "policyengine_api.services.simulation_analysis_service.SimulationAnalysisService._generate_simulation_analysis_prompt"
        ) as mock_generate_prompt:
            with patch(
                "policyengine_api.services.ai_analysis_service.AIAnalysisService.get_existing_analysis"
            ) as mock_get_existing:
                mock_get_existing.return_value = None
                with patch(
                    "policyengine_api.services.ai_analysis_service.AIAnalysisService.trigger_ai_analysis"
                ) as mock_trigger:
                    mock_trigger.return_value = (
                        s for s in ["Enhanced CPS analysis"]
                    )

                    response = execute_simulation_analysis("us")

                    assert response.status_code == 200
                    assert b"Enhanced CPS analysis" in response.data
                    mock_generate_prompt.assert_called_once_with(
                        "2023",
                        "enhanced_us",
                        "USD",
                        policy_details,
                        test_impact,
                        ["param1", "param2"],
                        [{"param1": 100}, {"param2": 200}],
                        True,
                        "2023",
                        "us",
                        "Test Policy",
                    )
