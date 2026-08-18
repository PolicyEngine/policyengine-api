import json
import os
from collections.abc import Generator
import time
from typing import Callable

import anthropic
from pydantic import BaseModel

from policyengine_api.runtime_cache.dependencies import get_runtime_cache_context
from policyengine_api.runtime_cache.core import record_cache_event
from policyengine_api.runtime_cache.repositories import (
    AIAnalysisCache,
    CachedAnalysis,
)


AI_ANALYSIS_MODEL = "claude-sonnet-4-20250514"


class StreamEvent(BaseModel):
    type: str


class TextEvent(StreamEvent):
    type: str = "text"
    stream: str


class ErrorEvent(StreamEvent):
    type: str = "error"
    error: str


class AIAnalysisService:
    """AI analysis operations with short, service-owned ORM scopes."""

    def __init__(
        self,
        analysis_cache: AIAnalysisCache | None = None,
        claude_client_factory: Callable[[], anthropic.Anthropic] | None = None,
    ) -> None:
        if analysis_cache is None:
            context = get_runtime_cache_context()
            analysis_cache = AIAnalysisCache(context.client, context.namespace)
        self._analysis_cache = analysis_cache
        self._claude_client_factory = claude_client_factory

    def get_existing_analysis(
        self,
        prompt: str,
    ) -> CachedAnalysis | None:
        return self._analysis_cache.get(prompt, model=AI_ANALYSIS_MODEL)

    def trigger_ai_analysis(
        self,
        prompt: str,
    ) -> Generator[str, None, None]:
        claude_client = (
            self._claude_client_factory()
            if self._claude_client_factory is not None
            else anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        )

        def generate():
            recompute_started_at = time.perf_counter()
            response_text = ""
            with claude_client.messages.stream(
                model=AI_ANALYSIS_MODEL,
                max_tokens=1500,
                temperature=0.0,
                system="You are an AI assistant analyzing policy data. Explain policies clearly and factually. Do not provide commentary, opinions, or quotes. Focus only on describing what the policies do and their direct impacts.",
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for event in stream:
                    if event.type == "error":
                        record_cache_event(
                            family="ai-analysis",
                            event="recompute-failed",
                            started_at=recompute_started_at,
                            severity="WARNING",
                        )
                        yield (
                            json.dumps(
                                ErrorEvent(error=event.error["type"]).model_dump()
                            )
                            + "\n"
                        )
                        return
                    if event.type == "text":
                        response_text += event.text
                        yield (
                            json.dumps(TextEvent(stream=event.text).model_dump()) + "\n"
                        )
            record_cache_event(
                family="ai-analysis",
                event="recompute",
                started_at=recompute_started_at,
            )
            self._analysis_cache.set(
                CachedAnalysis(
                    prompt=prompt,
                    analysis=response_text,
                    status="ok",
                ),
                model=AI_ANALYSIS_MODEL,
            )

        return generate()
