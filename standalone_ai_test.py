import os
import json
import anthropic
import openai
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Generator

# Load environment variables from .env file
load_dotenv()

# Stream event classes
class StreamEvent(BaseModel):
    type: str

class TextEvent(StreamEvent):
    type: str = "text"
    stream: str

class ErrorEvent(StreamEvent):
    type: str = "error"
    error: str


class AIService:
    """Simplified AI service for testing purposes"""
    
    def _call_claude_api(self, prompt: str) -> Generator[StreamEvent, None, None]:
        """
        Make an API call to Anthropic's Claude model and return a generator
        of stream events
        """
        try:
            # Configure a Claude client
            claude_client = anthropic.Anthropic(
                api_key=os.getenv("ANTHROPIC_API_KEY")
            )

            with claude_client.messages.stream(
                model="claude-3-5-sonnet-20240620",
                max_tokens=1500,
                temperature=0.0,
                system="Respond with a historical quote",
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for event in stream:
                    if event.type == "error":
                        error: dict[str, str] = event.error
                        error_type: str = error["type"]
                        yield ErrorEvent(error=error_type)
                        return
                    if event.type == "text":
                        yield TextEvent(stream=event.text)
        except Exception as e:
            yield ErrorEvent(error=str(e))

    def _call_openai_api(self, prompt: str) -> Generator[StreamEvent, None, None]:
        try:
            openai_client = openai.Client(
                api_key=os.getenv("OPENAI_API_KEY")
            )

            stream = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=1500,
                stream=True,
            )

            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    content = chunk.choices[0].delta.content
                    yield TextEvent(stream=content)

        except openai.OpenAIError as e:
            error_message = str(e)
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


def test_service_provider(provider):
    print(f"\nTesting AI Service with {provider} provider...")
    service = AIService()
    prompt = "What is the capital of France?"
    
    try:
        # Collect results
        results = []
        for response in service.trigger_ai_analysis(prompt, provider=provider):
            print(response)
            results.append(json.loads(response))
        
        # Check for errors in results
        errors = [r for r in results if r.get("type") == "error"]
        if errors:
            print(f"{provider} test completed with errors: {errors[0].get('error')}")
        else:
            print(f"{provider} test completed successfully.")
            
    except Exception as e:
        print(f"Error testing {provider}: {str(e)}")


if __name__ == "__main__":
    print("API Key Verification:")
    print(f"ANTHROPIC_API_KEY: {'Present' if os.getenv('ANTHROPIC_API_KEY') else 'Missing'}")
    print(f"OPENAI_API_KEY: {'Present' if os.getenv('OPENAI_API_KEY') else 'Missing'}")
    
    test_service_provider("claude")
    test_service_provider("openai") 