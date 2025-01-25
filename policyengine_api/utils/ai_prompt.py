from pathlib import Path
import yaml
import re

current_directory: Path = Path(__file__).parent
AI_TEMPLATE_DIRECTORY: Path = current_directory.parent.joinpath("ai_templates")


class AIPromptBase:
    """
    Base class for AI prompts that implements certain utility methods. Superclasses
    should define the following optional attributes/methods:

      generated_fields: set: Set of fields generated programmatically within
      _pre_transform_data

      non_parsed_input_fields: set: Set of fields that must be input but are not
      parseable from the prompt template

      _transform_data: Callable(data: dict) -> dict: Method to transform data before formatting

      data: dict: Data to be formatted into the prompt template
    """

    def __init__(
        self,
        template_file: str,
        template_dir: str | Path = AI_TEMPLATE_DIRECTORY,
    ):

        self.generated_fields: set = set()
        self.non_parsed_input_fields: set = set()

        self.all_fields: set = set()
        self.input_fields: set = set()

        self.data: dict = {}

        self.template_dir: Path = Path(template_dir)
        self.template_file: Path = Path(template_file)
        self.template_path: Path = Path(self.template_dir).joinpath(
            self.template_file
        )
        self._load_template()
        self._update_dependent_fields()

    def _load_template(self):
        try:
            with open(self.template_path) as f:
                self.template = yaml.safe_load(f)
            if not self.template.get("prompt"):
                raise KeyError("Template does not contain a 'prompt' key")
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Template file not found: {self.template_file}"
            )

    def _extract_all_fields(self):
        """
        Extract required keys from an AI prompt template's 'prompt' value.
        """
        # Match anything between curly braces
        pattern = r"\{([^}]*)\}"
        matches = set(re.findall(pattern, self.template["prompt"]))

        if not matches:
            raise KeyError("No fields found in prompt template")

        self.all_fields = matches

    def _check_missing_input_fields(self, data: dict):
        """
        Check if any required fields are missing from the data.
        """
        missing_fields = self.input_fields - set(data.keys())
        if missing_fields:
            raise KeyError(
                f"Missing required fields in data: {missing_fields}"
            )

    def _transform_data(self, data: dict):
        """
        Method to pre-transform data before formatting the prompt template.
        Should be overridden by subclasses, if necessary.
        """
        pass

    def get_prompt(self):
        try:
            return self.template["prompt"].format_map(self.data)
        except KeyError as e:
            raise KeyError(
                f"Unable to get prompt {self.template_file}: missing key in prompt template: {e}"
            )

    def _update_dependent_fields(self):
        """
        Updates fields that depend on generated_fields and non_parsed_input_fields.
        Should be called after modifying either of those fields.
        """
        self._extract_all_fields()
        self.input_fields = (
            self.all_fields - self.generated_fields
        ) | self.non_parsed_input_fields
