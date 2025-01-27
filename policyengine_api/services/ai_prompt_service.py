from pathlib import Path
from policyengine_api.ai_prompts import all_ai_prompts

current_directory: Path = Path(__file__).parent
AI_TEMPLATE_DIRECTORY: Path = current_directory.parent.joinpath("ai_templates")


class AIPromptService:
    all_prompts: dict[str, type] = {}

    def __init__(self):
        self._load_all_prompts()

    def _load_all_prompts(self):
        """
        Load all AI prompts from the database.
        """
        print("Loading all AI prompts")
        for prompt in all_ai_prompts:
            self.all_prompts[prompt.name] = prompt

    def get_prompt(self, name: str, input_data: dict) -> str | None:
        """
        Get an AI prompt with a given name, filled with the given data.
        """

        print(f"Getting AI prompt {name}")

        # Instantiate relevant prompt's class based on name
        prompt_class: type = self.all_prompts.get(name)
        if prompt_class is None:
            return None

        # Attempt to generate prompt
        prompt = prompt_class(data=input_data)

        # Return generated prompt
        return prompt.get_prompt()
