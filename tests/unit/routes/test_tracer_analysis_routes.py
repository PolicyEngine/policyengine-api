import pytest
from flask import json
from unittest.mock import patch

@patch("policyengine_api.services.tracer_analysis_service.local_database")
@patch(
    "policyengine_api.services.tracer_analysis_service.TracerAnalysisService.trigger_ai_analysis"
)
def test_execute_tracer_analysis_success(
    mock_trigger_ai_analysis, mock_db, rest_client
):
    mock_db.query.return_value.fetchone.return_value = {
        "tracer_output": json.dumps(
            ["disposable_income <1000>", "    market_income <1000>"]
        )
    }
    mock_trigger_ai_analysis.return_value = "AI analysis result"
    test_household_id = 1500

    # Set this to US current law
    test_policy_id = 2

    response = rest_client.post(
        "/us/tracer-analysis",
        json={
            "household_id": test_household_id,
            "policy_id": test_policy_id,
            "variable": "disposable_income",
        },
    )

    assert response.status_code == 200
    assert b"AI analysis result" in response.data


@patch("policyengine_api.services.tracer_analysis_service.local_database")
def test_execute_tracer_analysis_no_tracer(mock_db, rest_client):
    mock_db.query.return_value.fetchone.return_value = None

    response = rest_client.post(
        "/us/tracer-analysis",
        json={
            "household_id": "test_household",
            "policy_id": "test_policy",
            "variable": "disposable_income",
        },
    )

    assert response.status_code == 404
    assert (
        "No household simulation tracer found"
        in json.loads(response.data)["message"]
    )


@patch("policyengine_api.services.tracer_analysis_service.local_database")
@patch(
    "policyengine_api.services.tracer_analysis_service.TracerAnalysisService.trigger_ai_analysis"
)
def test_execute_tracer_analysis_ai_error(
    mock_trigger_ai_analysis, mock_db, rest_client
):
    mock_db.query.return_value.fetchone.return_value = {
        "tracer_output": json.dumps(
            ["disposable_income <1000>", "    market_income <1000>"]
        )
    }
    mock_trigger_ai_analysis.side_effect = Exception(KeyError)

    test_household_id = 1500
    test_policy_id = 2

    # Use the test client to make the request instead of calling the function directly
    response = rest_client.post(
        "/us/tracer-analysis",
        json={
            "household_id": test_household_id,
            "policy_id": test_policy_id,
            "variable": "disposable_income",
        },
    )

    assert response.status_code == 500
    assert json.loads(response.data)["status"] == "error"


# Test invalid country
def test_invalid_country(rest_client):
    response = rest_client.post(
        "/invalid_country/tracer-analysis",
        json={
            "household_id": "test_household",
            "policy_id": "test_policy",
            "variable": "disposable_income",
        },
    )
    assert response.status_code == 400
    assert b"Country invalid_country not found" in response.data
