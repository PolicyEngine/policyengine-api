import pytest
from flask import json
from unittest.mock import patch
from werkzeug.exceptions import BadRequest

# constants
VALID_HOUSEHOLD_ID = 123
VALID_POLICY_ID = 456
INVALID_HOUSEHOLD_ID = "abc123"
INVALID_POLICY_ID = "invalid-id"
TEST_VARIABLE = "disposable_income"
INVALID_VARIABLE = 123


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
            "household_id": VALID_HOUSEHOLD_ID,
            "policy_id": VALID_POLICY_ID,
            "variable": "disposable_income",
        },
    )

    assert response.status_code == 404
    assert (
        "No household simulation tracer found" in json.loads(response.data)["message"]
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


@patch("policyengine_api.services.tracer_analysis_service.local_database")
def test_invalid_variable_types(mock_db, rest_client):
    """Test that different non-string variable types are rejected"""
    invalid_variables = [
        123,
        None,
        {"key": "value"},
        ["list"],
        True,
    ]

    for invalid_var in invalid_variables:
        response = rest_client.post(
            "/us/tracer-analysis",
            json={
                "household_id": VALID_HOUSEHOLD_ID,
                "policy_id": VALID_POLICY_ID,
                "variable": invalid_var,
            },
        )
        assert response.status_code == 400
        assert "variable must be a string" in json.loads(response.data)["message"]


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


def test_invalid_household_id_format(rest_client):
    """Test that non-numeric household_id is rejected"""
    response = rest_client.post(
        "/us/tracer-analysis",
        json={
            "household_id": INVALID_HOUSEHOLD_ID,
            "policy_id": VALID_POLICY_ID,
            "variable": "disposable_income",
        },
    )
    assert response.status_code == 400
    assert (
        "household_id must be a numeric integer or string"
        in json.loads(response.data)["message"]
    )


def test_invalid_policy_id_format(rest_client):
    """Test that non-numeric policy_id is rejected"""
    response = rest_client.post(
        "/us/tracer-analysis",
        json={
            "household_id": VALID_HOUSEHOLD_ID,
            "policy_id": INVALID_POLICY_ID,
            "variable": "disposable_income",
        },
    )
    assert response.status_code == 400
    assert (
        "policy_id must be a numeric integer or string"
        in json.loads(response.data)["message"]
    )


def test_empty_household_id(rest_client):
    """Test that empty household_id is rejected"""
    response = rest_client.post(
        "/us/tracer-analysis",
        json={
            "household_id": "",
            "policy_id": VALID_POLICY_ID,
            "variable": "disposable_income",
        },
    )
    assert response.status_code == 400


def test_missing_required_fields(rest_client):
    """Test that missing required fields are rejected"""
    response = rest_client.post(
        "/us/tracer-analysis",
        json={
            # household_id missing
            "policy_id": VALID_POLICY_ID,
            "variable": "disposable_income",
        },
    )
    assert response.status_code == 400


def test_invalid_types(rest_client):
    """Test that invalid types are rejected"""
    response = rest_client.post(
        "/us/tracer-analysis",
        json={
            "household_id": None,  # Invalid type
            "policy_id": INVALID_POLICY_ID,
            "variable": "disposable_income",
        },
    )
    assert response.status_code == 400


def test_validate_tracer_analysis_payload_failure(rest_client):
    """Test handling of invalid payload from validate_tracer_analysis_payload"""
    response = rest_client.post(
        "/us/tracer-analysis",
        json={
            # Missing required field 'variable'
            "household_id": VALID_HOUSEHOLD_ID,
            "policy_id": VALID_POLICY_ID,
        },
    )
    assert response.status_code == 400
    assert "Missing required key: variable" in json.loads(response.data)["message"]
