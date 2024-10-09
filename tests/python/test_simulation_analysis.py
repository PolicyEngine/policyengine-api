import pytest
from unittest.mock import patch, MagicMock
from flask import Flask, jsonify
from policyengine_api.data import local_database
from policyengine_api.endpoints import execute_simulation_analysis


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    return app


def test_execute_simulation_analysis_existing_analysis(app, rest_client):
    test_impact = {
        "budget": 1000,
        "intra_decile": 0.1,
        "decile": 0.2,
        "poverty": {
            "poverty": 0.3,
            "deep_poverty": 0.4,
        },
        "poverty_by_gender": 0.5,
        "poverty_by_race": {"poverty": 0.6},
        "inequality": 0.7,
    }

    with app.test_request_context(
        json={
            "currency": "USD",
            "selected_version": "2023",
            "time_period": "2023",
            "impact": test_impact,
            "policy_label": "Test Policy",
            "policy": "policy details",
            "region": "US",
            "relevant_parameters": ["param1", "param2"],
            "relevant_parameter_baseline_values": {
                "param1": 100,
                "param2": 200,
            },
            "audience": "Normal",
        }
    ):
        with patch(
            "policyengine_api.endpoints.simulation_analysis.get_existing_analysis"
        ) as mock_get_existing:
            mock_get_existing.return_value = (s for s in ["Existing analysis"])

            response = execute_simulation_analysis("US")

            assert response.status_code == 200
            assert b"Existing analysis" in response.data


def test_execute_simulation_analysis_new_analysis(app, rest_client):
    test_impact = {
        "budget": 1000,
        "intra_decile": 0.1,
        "decile": 0.2,
        "poverty": {
            "poverty": 0.3,
            "deep_poverty": 0.4,
        },
        "poverty_by_gender": 0.5,
        "poverty_by_race": {"poverty": 0.6},
        "inequality": 0.7,
    }
    with app.test_request_context(
        json={
            "currency": "USD",
            "selected_version": "2023",
            "time_period": "2023",
            "impact": test_impact,
            "policy_label": "Test Policy",
            "policy": "policy details",
            "region": "US",
            "relevant_parameters": ["param1", "param2"],
            "relevant_parameter_baseline_values": {
                "param1": 100,
                "param2": 200,
            },
            "audience": "Normal",
        }
    ):
        with patch(
            "policyengine_api.endpoints.simulation_analysis.get_existing_analysis"
        ) as mock_get_existing:
            mock_get_existing.return_value = None
            with patch(
                "policyengine_api.endpoints.simulation_analysis.trigger_ai_analysis"
            ) as mock_trigger:
                mock_trigger.return_value = (s for s in ["New analysis"])

                response = execute_simulation_analysis("US")

                assert response.status_code == 200
                assert b"New analysis" in response.data


def test_execute_simulation_analysis_error(app, rest_client):
    test_impact = {
        "budget": 1000,
        "intra_decile": 0.1,
        "decile": 0.2,
        "poverty": {"poverty": 0.3, "deep_poverty": 0.4},
        "poverty_by_gender": 0.5,
        "poverty_by_race": {"poverty": 0.6},
        "inequality": 0.7,
    }
    with app.test_request_context(
        json={
            "currency": "USD",
            "selected_version": "2023",
            "time_period": "2023",
            "impact": test_impact,
            "policy_label": "Test Policy",
            "policy": "policy details",
            "region": "US",
            "relevant_parameters": ["param1", "param2"],
            "relevant_parameter_baseline_values": {
                "param1": 100,
                "param2": 200,
            },
            "audience": "Normal",
        }
    ):
        with patch(
            "policyengine_api.endpoints.simulation_analysis.get_existing_analysis"
        ) as mock_get_existing:
            mock_get_existing.return_value = None
            with patch(
                "policyengine_api.endpoints.simulation_analysis.trigger_ai_analysis"
            ) as mock_trigger:
                mock_trigger.side_effect = Exception("Test error")

                response = execute_simulation_analysis("us")

                assert response.status_code == 500


def test_execute_simulation_analysis_enhanced_cps(app, rest_client):
    test_impact = {
        "budget": 1000,
        "intra_decile": 0.1,
        "decile": 0.2,
        "poverty": {"poverty": 0.3, "deep_poverty": 0.4},
        "poverty_by_gender": 0.5,
        "poverty_by_race": {"poverty": 0.6},
        "inequality": 0.7,
    }
    with app.test_request_context(
        json={
            "currency": "USD",
            "selected_version": "2023",
            "time_period": "2023",
            "impact": test_impact,
            "policy_label": "Test Policy",
            "policy": "policy details",
            "region": "enhanced_cps_US",
            "relevant_parameters": ["param1", "param2"],
            "relevant_parameter_baseline_values": {
                "param1": 100,
                "param2": 200,
            },
            "audience": "Normal",
        }
    ):
        with patch(
            "policyengine_api.endpoints.simulation_analysis.generate_simulation_analysis_prompt"
        ) as mock_generate_prompt:
            with patch(
                "policyengine_api.endpoints.simulation_analysis.get_existing_analysis"
            ) as mock_get_existing:
                mock_get_existing.return_value = None
                with patch(
                    "policyengine_api.endpoints.simulation_analysis.trigger_ai_analysis"
                ) as mock_trigger:
                    mock_trigger.return_value = (
                        s for s in ["Enhanced CPS analysis"]
                    )

                    response = execute_simulation_analysis("US")

                    assert response.status_code == 200
                    assert b"Enhanced CPS analysis" in response.data
                    mock_generate_prompt.assert_called_once_with(
                        "2023",
                        "enhanced_cps_US",
                        "USD",
                        "policy details",
                        test_impact,
                        ["param1", "param2"],
                        {"param1": 100, "param2": 200},
                        True,
                        "2023",
                        "US",
                        "Test Policy",
                    )
