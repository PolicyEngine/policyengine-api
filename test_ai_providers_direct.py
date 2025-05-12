import os
import anthropic
import openai
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def test_claude_api():
    print("\nTesting Claude API...")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not found in environment variables")
        return
        
    try:
        # Configure a Claude client
        claude_client = anthropic.Anthropic(api_key=api_key)
        
        # Make a simple API request
        response = claude_client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=100,
            messages=[{"role": "user", "content": "What is the capital of France?"}]
        )
        
        print(f"Claude response: {response.content[0].text}")
        print("Claude API test completed successfully.")
    except anthropic.APIError as e:
        print(f"Claude API Error: {str(e)}")
    except Exception as e:
        print(f"Unexpected error testing Claude API: {str(e)}")

def test_openai_api():
    print("\nTesting OpenAI API...")
    api_key = os.getenv("OPENAI_API_KEY")
    
    if not api_key:
        print("Error: OPENAI_API_KEY not found in environment variables")
        return
        
    try:
        # Configure OpenAI client
        openai_client = openai.Client(api_key=api_key)
        
        # Make a simple API request
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "What is the capital of France?"}],
            max_tokens=100
        )
        
        print(f"OpenAI response: {response.choices[0].message.content}")
        print("OpenAI API test completed successfully.")
    except openai.OpenAIError as e:
        error_message = str(e)
        
        # Check for quota/billing error
        if "insufficient_quota" in error_message:
            print("OpenAI API Error: Quota exceeded or billing issue. Please check your OpenAI account.")
        else:
            print(f"OpenAI API Error: {error_message}")
    except Exception as e:
        print(f"Unexpected error testing OpenAI API: {str(e)}")

if __name__ == "__main__":
    print("API Key Verification:")
    print(f"ANTHROPIC_API_KEY: {'Present' if os.getenv('ANTHROPIC_API_KEY') else 'Missing'}")
    print(f"OPENAI_API_KEY: {'Present' if os.getenv('OPENAI_API_KEY') else 'Missing'}")
    
    test_claude_api()
    test_openai_api() 