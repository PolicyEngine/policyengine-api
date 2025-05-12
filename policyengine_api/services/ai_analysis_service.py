import anthropic
import os
import json
from typing import Generator, Optional
from policyengine_api.data import local_database
from pydantic import BaseModel
import openai
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


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

    def _call_claude_api(self, prompt: str) -> Generator[StreamEvent, None, None]:
        """
        Make an API call to Anthropic's Claude model and return a generator
        of stream events
        """
        # Configure a Claude client
        claude_client = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )

        response_text = ""

        with claude_client.messages.stream(
            model="claude-3-5-sonnet-20240620",
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
                    yield ErrorEvent(error=error_type)
                    return
                if event.type == "text":
                    response_text += event.text
                    yield TextEvent(stream=event.text)

        # Update the analysis record if no error occurred
        local_database.query(
            f"INSERT INTO analysis (prompt, analysis, status) VALUES (?, ?, ?)",
            (prompt, response_text, "ok"),
        )

    def _call_openai_api(self, prompt: str) -> Generator[StreamEvent, None, None]:
        """
        Make an API call to OpenAI's ChatGPT model and return a generator
        of stream events
        """
        # Configure OpenAI client
        openai_client = openai.Client(
            api_key=os.getenv("OPENAI_API_KEY")
        )

        response_text = ""

        try:
            # Create a streaming response
            stream = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=1500,
                stream=True,
            )

            # Process the streaming response
            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    content = chunk.choices[0].delta.content
                    response_text += content
                    yield TextEvent(stream=content)

            # Update the analysis record if no error occurred
            local_database.query(
                f"INSERT INTO analysis (prompt, analysis, status) VALUES (?, ?, ?)",
                (prompt, response_text, "ok"),
            )
        except openai.OpenAIError as e:
            error_message = str(e)
            
            # Check for quota/billing error
            if "insufficient_quota" in error_message:
                error_message = "OpenAI API quota exceeded or billing issue. Please check your OpenAI account."
            
            yield ErrorEvent(error=error_message)
        except Exception as e:
            yield ErrorEvent(error=str(e))

    def trigger_ai_analysis(self, prompt: str, provider: str = "claude") -> Generator[str, None, None]:
        """
        Trigger AI analysis with the specified provider
        
        Args:
            prompt: The prompt to send to the AI model
            provider: The AI provider to use ('claude' or 'openai')
            
        Returns:
            A generator that yields JSON-serialized stream events
        """
        def generate():
            stream_generator = None
            
            if provider.lower() == "claude":
                stream_generator = self._call_claude_api(prompt)
            elif provider.lower() == "openai":
                stream_generator = self._call_openai_api(prompt)
            else:
                yield json.dumps(ErrorEvent(error=f"Unsupported provider: {provider}").model_dump()) + "\n"
                return
                
            for event in stream_generator:
                yield json.dumps(event.model_dump()) + "\n"
                
        return generate()
