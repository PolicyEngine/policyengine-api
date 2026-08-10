import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from policyengine_api.data.v1_models import Analysis
from policyengine_api.services.ai_analysis_service import AIAnalysisService
from tests.fixtures.services.ai_analysis_service import parse_to_chunks

pytest_plugins = ["tests.fixtures.services.ai_analysis_service"]


class TestTriggerAIAnalysis:
    def test_claude_stream_runs_without_an_open_database_session(
        self,
        orm_session_factory,
    ):
        class TrackingSessions:
            def __init__(self, delegate):
                self.delegate = delegate
                self.active = 0

            @contextmanager
            def __call__(self):
                self.active += 1
                try:
                    with self.delegate() as session:
                        yield session
                finally:
                    self.active -= 1

            @contextmanager
            def begin(self):
                self.active += 1
                try:
                    with self.delegate.begin() as session:
                        yield session
                finally:
                    self.active -= 1

        sessions = TrackingSessions(orm_session_factory)

        class ClaudeStream:
            def __enter__(self):
                assert sessions.active == 0
                return self

            def __exit__(self, *args):
                return None

            def __iter__(self):
                assert sessions.active == 0
                yield SimpleNamespace(type="text", text="analysis")

        claude_client = SimpleNamespace(
            messages=SimpleNamespace(stream=lambda **kwargs: ClaudeStream())
        )
        service = AIAnalysisService(
            sessions,
            claude_client_factory=lambda: claude_client,
        )

        assert list(service.trigger_ai_analysis("prompt")) == [
            json.dumps({"type": "text", "stream": "analysis"}) + "\n"
        ]
        assert sessions.active == 0

        with orm_session_factory() as session:
            stored = session.scalar(select(Analysis).where(Analysis.prompt == "prompt"))
        assert stored is not None
        assert stored.analysis == "analysis"

    def test_trigger_ai_analysis_given_successful_streaming(
        self, mock_stream_text_events, orm_session_factory
    ):
        # GIVEN a series of successful text messages from the Claude API
        expected_response = "This is a historical quote."
        text_chunks = parse_to_chunks(expected_response)
        mock_stream_text_events(text_chunks=text_chunks)

        # WHEN we call trigger_ai_analysis
        prompt = "Tell me a historical quote"
        generator = AIAnalysisService(orm_session_factory).trigger_ai_analysis(prompt)

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
        generator = AIAnalysisService(orm_session_factory).trigger_ai_analysis(prompt)

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
