import pytest
from unittest.mock import patch, MagicMock
import json
import os
from policyengine_api.utils.ai_analysis import (
    trigger_ai_analysis,
    get_existing_analysis,
)


@patch("policyengine_api.utils.ai_analysis.anthropic.Anthropic")
@patch("policyengine_api.utils.ai_analysis.local_database")
def test_trigger_ai_analysis(mock_db, mock_anthropic):
    mock_client = MagicMock()
    mock_anthropic.return_value = mock_client
    mock_stream = MagicMock()
    mock_stream.text_stream = ["Test ", "response ", "from ", "AI"]
    mock_client.messages.stream.return_value.__enter__.return_value = (
        mock_stream
    )

    prompt = "Test prompt"
    generator = trigger_ai_analysis(prompt)

    # Check initial yield
    initial_data = json.loads(next(generator))
    assert initial_data["prompt"] == prompt
    assert initial_data["stream"] == ""

    # Check subsequent yields
    chunks = [json.loads(chunk)["stream"] for chunk in generator]
    assert chunks == ["Test ", "respo", "nse f", "rom A", "I"]

    # Check database insert
    mock_db.query.assert_called_once_with(
        f"INSERT INTO analysis (prompt, analysis, status) VALUES (?, ?, ?)",
        (prompt, "Test response from AI", "ok"),
    )

    # Check Anthropic API call
    mock_client.messages.stream.assert_called_once_with(
        model="claude-3-5-sonnet-20240620",
        max_tokens=1500,
        temperature=0.0,
        system="Respond with a historical quote",
        messages=[{"role": "user", "content": prompt}],
    )


@patch("policyengine_api.utils.ai_analysis.local_database")
@patch("policyengine_api.utils.ai_analysis.time.sleep")
def test_get_existing_analysis_found(mock_sleep, mock_db):
    mock_db.query.return_value.fetchone.return_value = {
        "analysis": "Existing analysis"
    }

    prompt = "Test prompt"
    generator = get_existing_analysis(prompt)

    # Check initial yield
    initial_data = json.loads(next(generator))
    assert initial_data["prompt"] == prompt
    assert initial_data["stream"] == ""

    # Check subsequent yields
    chunks = [json.loads(chunk)["stream"] for chunk in generator]
    assert chunks == ["Exist", "ing a", "nalys", "is"]

    # Check database query
    mock_db.query.assert_called_once_with(
        f"SELECT analysis FROM analysis WHERE prompt = ?",
        (prompt,),
    )

    # Check that sleep was called for each chunk
    assert mock_sleep.call_count == 4


@patch("policyengine_api.utils.ai_analysis.local_database")
def test_get_existing_analysis_not_found(mock_db):
    mock_db.query.return_value.fetchone.return_value = None

    prompt = "Test prompt"
    result = get_existing_analysis(prompt)

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
@patch("policyengine_api.utils.ai_analysis.anthropic.Anthropic")
def test_trigger_ai_analysis_error(mock_anthropic):
    mock_client = MagicMock()
    mock_anthropic.return_value = mock_client
    mock_client.messages.stream.side_effect = Exception("API Error")

    prompt = "Test prompt"
    generator = trigger_ai_analysis(prompt)

    # Check initial yield
    initial_data = json.loads(next(generator))
    assert initial_data["prompt"] == prompt

    # The generator should stop after the initial yield due to the error
    with pytest.raises(Exception, match="API Error"):
        list(generator)
