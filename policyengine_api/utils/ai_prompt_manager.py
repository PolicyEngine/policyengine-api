from pathlib import Path
import yaml

AI_PROMPT_DIRECTORY = "ai_prompts"

class DefaultDict(dict):
    """
    Python's String.format_map() raises on missing keys; instead,
    return the key as a placeholder.
    """
    def __missing__(self, key):
        return '{' + key + '}'

class AIPromptManager:
    def __init__(self, templates_dir: str = AI_PROMPT_DIRECTORY):
        self.templates_dir = Path(templates_dir)
        self._load_templates()
    
    def _load_templates(self):
        self.templates = {}
        for template_file in self.templates_dir.glob("*.yaml"):
            with open(template_file) as f:
                self.templates[template_file.stem] = yaml.safe_load(f)
    
    def get_prompt(self, template_name: str, **kwargs):
        template: str = self.templates[template_name]["prompt_template"]
        try:
          return template.format_map(DefaultDict(**kwargs))
        except KeyError as e:
          raise KeyError(f"Missing key in prompt template: {e}")
          