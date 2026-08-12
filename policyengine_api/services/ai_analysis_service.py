import json
import os
from collections.abc import Generator
from typing import Callable

import anthropic
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import Analysis


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
        session_factory: sessionmaker[Session] | None = None,
        claude_client_factory: Callable[[], anthropic.Anthropic] | None = None,
    ) -> None:
        self._injected_session_factory = session_factory
        self._claude_client_factory = claude_client_factory

    @property
    def _sessions(self) -> sessionmaker[Session]:
        return self._injected_session_factory or get_v1_session_factory(local=True)

    def get_existing_analysis(
        self,
        prompt: str,
    ) -> Analysis | None:
        with self._sessions() as session:
            return self._get_existing_analysis(session, prompt)

    @staticmethod
    def _get_existing_analysis(
        session: Session,
        prompt: str,
    ) -> Analysis | None:
        return session.scalar(
            select(Analysis)
            .where(
                Analysis.prompt == prompt,
                Analysis.status.in_(("complete", "ok")),
            )
            .order_by(Analysis.prompt_id.desc())
        )

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
            with self._sessions.begin() as session:
                session.add(
                    Analysis(
                        prompt=prompt,
                        analysis=response_text,
                        status="ok",
                    )
                )

        return generate()
