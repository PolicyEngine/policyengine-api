import json
from types import SimpleNamespace

import pytest

from policyengine_api.runtime_cache.core import CacheNamespace
from policyengine_api.runtime_cache.fake import InMemoryCacheBackend
from policyengine_api.runtime_cache.repositories import AIAnalysisCache
from policyengine_api.services.ai_analysis_service import (
    AI_ANALYSIS_MODEL,
    AIAnalysisService,
)
from tests.fixtures.services.ai_analysis_service import parse_to_chunks

pytest_plugins = ["tests.fixtures.services.ai_analysis_service"]


def _cache() -> AIAnalysisCache:
    return AIAnalysisCache(
        InMemoryCacheBackend(),
        CacheNamespace("test", "api"),
    )


class TestTriggerAIAnalysis:
    def test_claude_stream_caches_only_after_successful_completion(self):
        cache = _cache()

        class ClaudeStream:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def __iter__(self):
                assert cache.get("prompt", model=AI_ANALYSIS_MODEL) is None
                yield SimpleNamespace(type="text", text="analysis")

        claude_client = SimpleNamespace(
            messages=SimpleNamespace(stream=lambda **kwargs: ClaudeStream())
        )
        service = AIAnalysisService(
            cache,
            claude_client_factory=lambda: claude_client,
        )

        assert list(service.trigger_ai_analysis("prompt")) == [
            json.dumps({"type": "text", "stream": "analysis"}) + "\n"
        ]
        stored = cache.get("prompt", model=AI_ANALYSIS_MODEL)
        assert stored is not None
        assert stored.analysis == "analysis"

    def test_trigger_ai_analysis_given_successful_streaming(
        self, mock_stream_text_events
    ):
        # GIVEN a series of successful text messages from the Claude API
        expected_response = "This is a historical quote."
        text_chunks = parse_to_chunks(expected_response)
        mock_stream_text_events(text_chunks=text_chunks)

        # WHEN we call trigger_ai_analysis
        prompt = "Tell me a historical quote"
        cache = _cache()
        generator = AIAnalysisService(cache).trigger_ai_analysis(prompt)

        # THEN it should yield the expected chunks
        results = list(generator)

        # Verify each yielded chunk
        for i, chunk in enumerate(results):
            if i < len(text_chunks):
                expected_chunk = (
                    json.dumps({"type": "text", "stream": text_chunks[i][:5]}) + "\n"
                )
                assert chunk == expected_chunk

        analysis_record = cache.get(prompt, model=AI_ANALYSIS_MODEL)

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
    def test_trigger_ai_analysis_given_error(self, mock_stream_error_event, error_type):
        # GIVEN an overloaded_error event from the Claude API
        mock_stream_error_event(error_type)

        # WHEN we call trigger_ai_analysis
        prompt = "Tell me a historical quote about erroneous systems"
        cache = _cache()
        generator = AIAnalysisService(cache).trigger_ai_analysis(prompt)

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

        assert cache.get(prompt, model=AI_ANALYSIS_MODEL) is None
