import json
import os
from unittest.mock import MagicMock, patch

import pytest

from policyengine_api.services.ai_analysis_service import AIAnalysisService


def test_get_existing_analysis_found():
    analyses = MagicMock()
    analyses.get.return_value = "Existing analysis"
    service = AIAnalysisService(analyses)

    output = service.get_existing_analysis("Test prompt")

    assert output == json.dumps("Existing analysis")
    analyses.get.assert_called_once_with("Test prompt")


def test_get_existing_analysis_not_found():
    analyses = MagicMock()
    analyses.get.return_value = None
    service = AIAnalysisService(analyses)

    assert service.get_existing_analysis("Test prompt") is None
    analyses.get.assert_called_once_with("Test prompt")


def test_anthropic_api_key():
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test_key"}):
        assert os.getenv("ANTHROPIC_API_KEY") == "test_key"


@patch("policyengine_api.services.ai_analysis_service.anthropic.Anthropic")
def test_trigger_ai_analysis_error(mock_anthropic):
    mock_client = MagicMock()
    mock_anthropic.return_value = mock_client
    mock_client.messages.stream.side_effect = Exception("API Error")

    generator = AIAnalysisService(MagicMock()).trigger_ai_analysis("Test prompt")

    with pytest.raises(Exception, match="API Error"):
        list(generator)
