import pytest
from flask import Flask, json
from unittest.mock import patch, MagicMock
from policyengine_api.endpoints import execute_tracer_analysis
from policyengine_api.utils.tracer_analysis import parse_tracer_output
from policyengine_api.country import COUNTRY_PACKAGE_VERSIONS

@pytest.fixture
def app():
    app = Flask(__name__)
    app.config['TESTING'] = True
    return app

# Test cases for parse_tracer_output function
def test_parse_tracer_output():

    tracer_output = [
        "only_government_benefit <1500>",
        "    market_income <1000>",
        "        employment_income <1000>",
        "            main_employment_income <1000 >",
        "    non_market_income <500>",
        "        pension_income <500>",
    ]
    
    result = parse_tracer_output(tracer_output, "only_government_benefit")
    assert result == tracer_output
    
    result = parse_tracer_output(tracer_output, "market_income")
    assert result == tracer_output[1:4]
    
    result = parse_tracer_output(tracer_output, "non_market_income")
    assert result == tracer_output[4:]

# Test cases for execute_tracer_analysis function
@patch('policyengine_api.endpoints.tracer_analysis.local_database')
@patch('policyengine_api.endpoints.tracer_analysis.trigger_ai_analysis')
def test_execute_tracer_analysis_success(mock_trigger_ai_analysis, mock_db, app, rest_client):
    mock_db.query.return_value.fetchone.return_value = {
        "tracer_output": json.dumps(["disposable_income <1000>", "    market_income <1000>"])
    }
    mock_trigger_ai_analysis.return_value = "AI analysis result"
    test_household_id = 1500

    # Set this to US current law
    test_policy_id = 2

    with app.test_request_context('/us/tracer_analysis', json={
        "household_id": test_household_id,
        "policy_id": test_policy_id,
        "variable": "disposable_income"
    }):
        response = execute_tracer_analysis("us")

    assert response.status_code == 200
    assert b"AI analysis result" in response.data

@patch('policyengine_api.endpoints.tracer_analysis.local_database')
def test_execute_tracer_analysis_no_tracer(mock_db, app, rest_client):
    mock_db.query.return_value.fetchone.return_value = None

    with app.test_request_context('/us/tracer_analysis', json={
        "household_id": "test_household",
        "policy_id": "test_policy",
        "variable": "disposable_income"
    }):
        response = execute_tracer_analysis("us")
    
    assert response.status_code == 404
    assert "no household simulation tracer found" in response.response["message"]

@patch('policyengine_api.endpoints.tracer_analysis.local_database')
@patch('policyengine_api.endpoints.tracer_analysis.trigger_ai_analysis')
def test_execute_tracer_analysis_ai_error(mock_trigger_ai_analysis, mock_db, app, rest_client):
    mock_db.query.return_value.fetchone.return_value = {
        "tracer_output": json.dumps(["disposable_income <1000>", "    market_income <1000>"])
    }
    mock_trigger_ai_analysis.side_effect = Exception(KeyError)

    test_household_id = 1500

    # Set this to US current law
    test_policy_id = 2

    with app.test_request_context('/us/tracer_analysis', json={
        "household_id": test_household_id,
        "policy_id": test_policy_id,
        "variable": "disposable_income"
    }):
        response = execute_tracer_analysis("us")
    
    assert response.status_code == 500
    assert "Error computing analysis" in response.response["message"]

# Test invalid country
def test_invalid_country(rest_client):
    response = rest_client.post('/invalid_country/tracer_analysis', json={
        "household_id": "test_household",
        "policy_id": "test_policy",
        "variable": "disposable_income"
    })
    assert response.status_code == 404
    assert b"Country invalid_country not found" in response.data