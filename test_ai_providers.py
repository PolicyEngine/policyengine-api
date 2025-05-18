from policyengine_api.services.ai_analysis_service import AIAnalysisService

def test_ai_provider(provider):
    print(f"\nTesting {provider} API...")
    service = AIAnalysisService()
    prompt = "What is the capital of France?"
    generator = service.trigger_ai_analysis(prompt, provider=provider)
    
    try:
        for response in generator():
            print(response)
        print(f"{provider} test completed successfully.")
    except Exception as e:
        print(f"Error testing {provider}: {str(e)}")

if __name__ == "__main__":
    test_ai_provider("claude")
    test_ai_provider("openai") 