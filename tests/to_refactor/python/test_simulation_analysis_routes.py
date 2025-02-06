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


def test_execute_simulation_analysis_existing_analysis(rest_client):

    with patch(
        "policyengine_api.services.ai_analysis_service.AIAnalysisService.get_existing_analysis"
    ) as mock_get_existing:
        mock_get_existing.return_value = (s for s in ["Existing analysis"])

        response = rest_client.post("/us/simulation-analysis", json=test_json)

        assert response.status_code == 200
        assert b"Existing analysis" in response.data


def test_execute_simulation_analysis_new_analysis(rest_client):
    with patch(
        "policyengine_api.services.ai_analysis_service.AIAnalysisService.get_existing_analysis"
    ) as mock_get_existing:
        mock_get_existing.return_value = None
        with patch(
            "policyengine_api.services.simulation_analysis_service.AIAnalysisService.trigger_ai_analysis"
        ) as mock_trigger:
            mock_trigger.return_value = (s for s in ["New analysis"])

            response = rest_client.post(
                "/us/simulation-analysis", json=test_json
            )

            assert response.status_code == 200
            assert b"New analysis" in response.data


def test_execute_simulation_analysis_error(rest_client):
    with patch(
        "policyengine_api.services.ai_analysis_service.AIAnalysisService.get_existing_analysis"
    ) as mock_get_existing:
        mock_get_existing.return_value = None
        with patch(
            "policyengine_api.services.ai_analysis_service.AIAnalysisService.trigger_ai_analysis"
        ) as mock_trigger:
            mock_trigger.side_effect = Exception("Test error")

            response = rest_client.post(
                "/us/simulation-analysis", json=test_json
            )

            assert response.status_code == 500
            assert b"Test error" in response.data


def test_execute_simulation_analysis_enhanced_cps(rest_client):
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

                response = rest_client.post(
                    "/us/simulation-analysis", json=test_json_enhanced_us
                )

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
