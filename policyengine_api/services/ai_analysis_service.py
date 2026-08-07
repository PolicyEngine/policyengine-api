import json
import os
from collections.abc import Generator
from contextlib import contextmanager

import anthropic
from pydantic import BaseModel

from policyengine_api.data.orm import build_v1_session_manager
from policyengine_api.data.v1_daos import AnalysisDAO, V1UnitOfWork


class StreamEvent(BaseModel):
    type: str


class TextEvent(StreamEvent):
    type: str = "text"
    stream: str


class ErrorEvent(StreamEvent):
    type: str = "error"
    error: str


class AIAnalysisService:
    def __init__(
        self,
        analyses: AnalysisDAO | None = None,
        *,
        unit_of_work: V1UnitOfWork | None = None,
    ):
        self._analyses = analyses
        self._unit_of_work = unit_of_work

    @property
    def unit_of_work(self) -> V1UnitOfWork:
        if self._unit_of_work is None:
            self._unit_of_work = V1UnitOfWork(build_v1_session_manager(local=True))
        return self._unit_of_work

    @contextmanager
    def _analysis_repository(self, *, write: bool = False):
        if self._analyses is not None:
            yield self._analyses
            return
        boundary = self.unit_of_work.transaction if write else self.unit_of_work.read
        with boundary() as daos:
            yield daos.analyses

    def get_existing_analysis(self, prompt: str) -> str | None:
        with self._analysis_repository() as analyses:
            analysis = analyses.get(prompt)
        return json.dumps(analysis) if analysis is not None else None

    def trigger_ai_analysis(self, prompt: str) -> Generator[str, None, None]:
        claude_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        def generate():
            response_text = ""
            with claude_client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                temperature=0.0,
                system="You are an AI assistant analyzing policy data. Explain policies clearly and factually. Do not provide commentary, opinions, or quotes. Focus only on describing what the policies do and their direct impacts.",
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for event in stream:
                    if event.type == "error":
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
            with self._analysis_repository(write=True) as analyses:
                analyses.store(prompt, response_text, "ok")

        return generate()
