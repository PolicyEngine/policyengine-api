from typing import Callable, Any
from policyengine_api.ai_prompts.simulation_analysis_prompt import (
    generate_simulation_analysis_prompt,
)

AIPrompt = Callable[[dict[str, Any]], str]

ALL_AI_PROMPTS: dict[str, AIPrompt] = {
    "simulation_analysis": generate_simulation_analysis_prompt,
}


class AIPromptService:

    def get_prompt(self, name: str, input_data: dict) -> str | None:
        """
        Get an AI prompt with a given name, filled with the given data.
        """

        if name in ALL_AI_PROMPTS:
            return ALL_AI_PROMPTS[name](input_data)

        return None
