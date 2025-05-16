from policyengine_api.services.ai_analysis_service import AIAnalysisService, TextEvent, ErrorEvent
import json
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Override database operation to prevent errors
class TestAIAnalysisService(AIAnalysisService):
    def _call_claude_api(self, prompt: str):
        # Configure a Claude client
        import anthropic
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
                if event.type == "error":
                    error: dict[str, str] = event.error
                    error_type: str = error["type"]
                    yield ErrorEvent(error=error_type)
                    return
                if event.type == "text":
                    response_text += event.text
                    yield TextEvent(stream=event.text)
        
        # Skip database operations
        # local_database.query(...)

    def _call_openai_api(self, prompt: str):
        # Configure OpenAI client
        import openai
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

            # Skip database operations
            # local_database.query(...)
        except openai.OpenAIError as e:
            error_message = str(e)
            
            # Check for quota/billing error
            if "insufficient_quota" in error_message:
                error_message = "OpenAI API quota exceeded or billing issue. Please check your OpenAI account."
            
            yield ErrorEvent(error=error_message)
        except Exception as e:
            yield ErrorEvent(error=str(e))

def test_service_provider(provider):
    print(f"\nTesting AIAnalysisService with {provider} provider...")
    service = TestAIAnalysisService()
    prompt = "What is the capital of France?"
    
    try:
        # Create the generator
        generator = service.trigger_ai_analysis(prompt, provider=provider)
        
        # Collect results
        results = []
        for response in generator():
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
    test_service_provider("claude")
    test_service_provider("openai") 