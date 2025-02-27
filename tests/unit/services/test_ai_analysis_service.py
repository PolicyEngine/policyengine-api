import json
from policyengine_api.services.ai_analysis_service import AIAnalysisService
from tests.fixtures.services.ai_analysis_service import (
    mock_stream_text_events,
    mock_stream_error_event,
    patch_anthropic,
    parse_to_chunks,
)

# Initialize the service
service = AIAnalysisService()


class TestTriggerAIAnalysis:

    def test_trigger_ai_analysis_given_successful_streaming(
        self, mock_stream_text_events, test_db
    ):
        # GIVEN a series of successful text messages from the Claude API
        expected_response = "This is a historical quote."
        text_chunks = parse_to_chunks(expected_response)
        mock_client = mock_stream_text_events(text_chunks=text_chunks)

        # WHEN we call trigger_ai_analysis
        prompt = "Tell me a historical quote"
        generator = service.trigger_ai_analysis(prompt)

        # THEN it should yield the expected chunks
        results = list(generator)

        # Verify each yielded chunk
        for i, chunk in enumerate(results):
            if i < len(text_chunks):
                expected_chunk = (
                    json.dumps({"type": "text", "stream": text_chunks[i][:5]})
                    + "\n"
                )
                assert chunk == expected_chunk

        # Verify the database was updated with the complete response
        analysis_record = test_db.query(
            "SELECT * FROM analysis WHERE prompt = ?", (prompt,)
        ).fetchone()

        assert analysis_record is not None
        assert analysis_record["analysis"] == expected_response
        assert analysis_record["status"] == "ok"

    def test_trigger_ai_analysis_given_overloaded_error(
        self, mock_stream_error_event, test_db
    ):
        # GIVEN an overloaded_error event from the Claude API
        mock_client = mock_stream_error_event("overloaded_error")

        # WHEN we call trigger_ai_analysis
        prompt = "Tell me a historical quote about overloaded systems"
        generator = service.trigger_ai_analysis(prompt)

        # THEN it should yield the expected error message
        results = list(generator)

        # Verify the error message
        expected_error = (
            json.dumps(
                {
                    "type": "error",
                    "stream": "Claude, our partner service, is currently overloaded. Please try again later.",
                }
            )
            + "\n"
        )
        assert results[0] == expected_error

        # Verify the database was not updated
        analysis_record = test_db.query(
            "SELECT * FROM analysis WHERE prompt = ?", (prompt,)
        ).fetchone()

        assert analysis_record is None

    def test_trigger_ai_analysis_given_api_error(
        self, mock_stream_error_event, test_db
    ):
        # GIVEN an api_error event from the Claude API
        mock_client = mock_stream_error_event("api_error")

        # WHEN we call trigger_ai_analysis
        prompt = "Tell me a historical quote about API errors"
        generator = service.trigger_ai_analysis(prompt)

        # THEN it should yield the expected error message
        results = list(generator)

        # Verify the error message
        expected_error = (
            json.dumps(
                {
                    "type": "error",
                    "stream": "Claude, our partner service, is currently experiencing an error. Please try again later.",
                }
            )
            + "\n"
        )
        assert results[0] == expected_error

        # Verify the database was not updated
        analysis_record = test_db.query(
            "SELECT * FROM analysis WHERE prompt = ?", (prompt,)
        ).fetchone()

        assert analysis_record is None

    def test_trigger_ai_analysis_given_unknown_error(
        self, mock_stream_error_event, test_db
    ):
        # GIVEN an unknown error event from the Claude API
        mock_client = mock_stream_error_event("unknown_error")

        # WHEN we call trigger_ai_analysis
        prompt = "Tell me a historical quote about unknown errors"
        generator = service.trigger_ai_analysis(prompt)

        # THEN it should yield the default error message
        results = list(generator)

        # Verify the error message
        expected_error = (
            json.dumps(
                {
                    "type": "error",
                    "stream": "The AI serice has experienced an error.",
                }
            )
            + "\n"
        )
        assert results[0] == expected_error

        # Verify the database was not updated
        analysis_record = test_db.query(
            "SELECT * FROM analysis WHERE prompt = ?", (prompt,)
        ).fetchone()

        assert analysis_record is None
