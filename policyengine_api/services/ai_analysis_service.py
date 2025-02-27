import anthropic
import os
import json
from typing import Generator, Optional, Literal
from policyengine_api.data import local_database
from pydantic import BaseModel


class StreamEvent(BaseModel):
    type: Literal["text", "error"] = "text"
    stream: str


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
            chunk_size = 5
            response_text = ""
            buffer = ""

            with claude_client.messages.stream(
                model="claude-3-5-sonnet-20240620",
                max_tokens=1500,
                temperature=0.0,
                system="Respond with a historical quote",
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for event in stream:
                    if event.type == "text":
                        buffer += event.text
                        response_text += event.text
                        while len(buffer) >= chunk_size:
                            chunk = buffer[:chunk_size]
                            buffer = buffer[chunk_size:]
                            return_event = StreamEvent(stream=chunk)
                            yield json.dumps(return_event.model_dump()) + "\n"
                    # Docs on structure of Anthropic error events at https://docs.anthropic.com/en/api/messages-streaming#error-events
                    elif event.type == "error":
                        error: dict[str, str] = event.error
                        error_type: str = error["type"]
                        match error_type:
                            case "overloaded_error":
                                return_msg = "Claude, our partner service, is currently overloaded. Please try again later."
                            case "api_error":
                                return_msg = "Claude, our partner service, is currently experiencing an error. Please try again later."
                            case _:
                                return_msg = (
                                    "The AI serice has experienced an error."
                                )
                        return_event = StreamEvent(
                            type=event.type, stream=return_msg
                        )
                        yield json.dumps(return_event.model_dump()) + "\n"
                        return

            if buffer:
                return_event = StreamEvent(stream=buffer)
                yield json.dumps(return_event.model_dump()) + "\n"

            # Finally, update the analysis record and return
            local_database.query(
                f"INSERT INTO analysis (prompt, analysis, status) VALUES (?, ?, ?)",
                (prompt, response_text, "ok"),
            )

        return generate()
