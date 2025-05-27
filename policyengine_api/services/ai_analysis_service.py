import anthropic
import os
import json
from typing import Generator, Optional, Literal
from policyengine_api.data import local_database
from pydantic import BaseModel


class StreamEvent(BaseModel):
    type: str


class TextEvent(StreamEvent):
    type: str = "text"
    stream: str


class ErrorEvent(StreamEvent):
    type: str = "error"
    error: str


class AIAnalysisService:
    """
    Base class for various AI analysis-based services,
    including SimulationAnalysisService, that connects with the analysis
    local database table
    """

    def get_existing_analysis(self, prompt: str) -> Optional[str]:
        """
        Get existing analysis from the local database
        """

        analysis = local_database.query(
            f"SELECT analysis FROM analysis WHERE prompt = ?",
            (prompt,),
        ).fetchone()

        if analysis is None:
            return None

        return json.dumps(analysis["analysis"])

    def trigger_ai_analysis(self, prompt: str) -> Generator[str, None, None]:

        # Configure a Claude client
        claude_client = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )

        def generate():
            response_text = ""

            with claude_client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                temperature=0.0,
                system="Respond with a historical quote",
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for event in stream:
                    # Docs on structure of Anthropic error events at https://docs.anthropic.com/en/api/messages-streaming#error-events
                    if event.type == "error":
                        error: dict[str, str] = event.error
                        error_type: str = error["type"]
                        return_event = ErrorEvent(error=error_type)
                        yield json.dumps(return_event.model_dump()) + "\n"
                        return
                    if event.type == "text":
                        response_text += event.text
                        return_event = TextEvent(stream=event.text)
                        yield json.dumps(return_event.model_dump()) + "\n"

            # Update the analysis record and return if no error occurred
            local_database.query(
                f"INSERT INTO analysis (prompt, analysis, status) VALUES (?, ?, ?)",
                (prompt, response_text, "ok"),
            )

        return generate()
