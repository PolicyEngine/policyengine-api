import pytest
from unittest.mock import patch, MagicMock
import json
import os
from policyengine_api.services.ai_analysis_service import AIAnalysisService

test_ai_service = AIAnalysisService()


@patch("policyengine_api.services.ai_analysis_service.local_database")
def test_get_existing_analysis_found(mock_db):
    mock_db.query.return_value.fetchone.return_value = {"analysis": "Existing analysis"}

    prompt = "Test prompt"
    output = test_ai_service.get_existing_analysis(prompt)

    assert output == json.dumps("Existing analysis")

    # Check database query
    mock_db.query.assert_called_once_with(
        f"SELECT analysis FROM analysis WHERE prompt = ?",
        (prompt,),
    )


@patch("policyengine_api.services.ai_analysis_service.local_database")
def test_get_existing_analysis_not_found(mock_db):
    mock_db.query.return_value.fetchone.return_value = None

    prompt = "Test prompt"
    result = test_ai_service.get_existing_analysis(prompt)

    assert result is None
    mock_db.query.assert_called_once_with(
        f"SELECT analysis FROM analysis WHERE prompt = ?",
        (prompt,),
    )


# Additional test to check environment variable
def test_anthropic_api_key():
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test_key"}):
        assert os.getenv("ANTHROPIC_API_KEY") == "test_key"


# Test error handling in trigger_ai_analysis
@patch("policyengine_api.services.ai_analysis_service.anthropic.Anthropic")
def test_trigger_ai_analysis_error(mock_anthropic):
    mock_client = MagicMock()
    mock_anthropic.return_value = mock_client
    mock_client.messages.stream.side_effect = Exception("API Error")

    prompt = "Test prompt"
    generator = test_ai_service.trigger_ai_analysis(prompt)

    # The generator should stop after the initial yield due to the error
    with pytest.raises(Exception, match="API Error"):
        list(generator)
