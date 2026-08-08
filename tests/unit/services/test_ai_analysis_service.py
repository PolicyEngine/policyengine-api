import json
from sqlalchemy import select

from policyengine_api.data.v1_models import Analysis
from policyengine_api.services.ai_analysis_service import AIAnalysisService
from tests.fixtures.services.ai_analysis_service import parse_to_chunks
import pytest

pytest_plugins = ["tests.fixtures.services.ai_analysis_service"]

# Initialize the service
service = AIAnalysisService()


class TestTriggerAIAnalysis:
    def test_trigger_ai_analysis_given_successful_streaming(
        self, mock_stream_text_events, orm_session_factory
    ):
        # GIVEN a series of successful text messages from the Claude API
        expected_response = "This is a historical quote."
        text_chunks = parse_to_chunks(expected_response)
        mock_stream_text_events(text_chunks=text_chunks)

        # WHEN we call trigger_ai_analysis
        prompt = "Tell me a historical quote"
        generator = service.trigger_ai_analysis(prompt, orm_session_factory)

        # THEN it should yield the expected chunks
        results = list(generator)

        # Verify each yielded chunk
        for i, chunk in enumerate(results):
            if i < len(text_chunks):
                expected_chunk = (
                    json.dumps({"type": "text", "stream": text_chunks[i][:5]}) + "\n"
                )
                assert chunk == expected_chunk

        # Verify the database was updated with the complete response
        with orm_session_factory() as session:
            analysis_record = session.scalar(
                select(Analysis).where(Analysis.prompt == prompt)
            )

        assert analysis_record is not None
        assert analysis_record.analysis == expected_response
        assert analysis_record.status == "ok"

    @pytest.mark.parametrize(
        "error_type",
        [
            "overloaded_error",
            "api_error",
            "unknown_error",
        ],
    )
    def test_trigger_ai_analysis_given_error(
        self, mock_stream_error_event, orm_session_factory, error_type
    ):
        # GIVEN an overloaded_error event from the Claude API
        mock_stream_error_event(error_type)

        # WHEN we call trigger_ai_analysis
        prompt = "Tell me a historical quote about erroneous systems"
        generator = service.trigger_ai_analysis(prompt, orm_session_factory)

        # THEN it should yield the expected error message
        results = list(generator)

        # Verify the error message
        expected_error = (
            json.dumps(
                {
                    "type": "error",
                    "error": error_type,
                }
            )
            + "\n"
        )
        assert results[0] == expected_error

        # Verify the database was not updated
        with orm_session_factory() as session:
            analysis_record = session.scalar(
                select(Analysis).where(Analysis.prompt == prompt)
            )

        assert analysis_record is None
