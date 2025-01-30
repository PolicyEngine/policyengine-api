from pathlib import Path
from policyengine_api.utils.ai_prompt import AIPromptBase
import pytest
import yaml


# class TestInit:
#     def test_load_template_correct_(self):
#         link = Path("tests/fixtures/test_ai_prompt/test_template_correct.yaml")
#         
#         ai_prompt = AIPromptBase(link)
#         assert ai_prompt.template == {'prompt': 'This is a test prompt with {field1} and {field2}'}


def construct_filepath(filename: str) -> Path:
    tests_directory: Path = Path(__file__).parent.parent.parent
    return tests_directory.joinpath(f"fixtures/test_ai_prompt")

link_correct = construct_filepath("test_template_correct.yaml")


class TestLoadTemplate:
    
    valid_template = {'prompt': 'This is a test prompt with {field1} and {field2}'}
    invalid_template_missing_prompt = {'dworkin': 'This is a test prompt with {field1} and {field2}'}
    
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        
        # Setup - create temp file
        self.ai_prompt = object.__new__(AIPromptBase)
        self.ai_prompt.template_dir = tmp_path
        self.ai_prompt.template_file = Path("test_template_correct.yaml")
        self.ai_prompt.template_path = self.ai_prompt.template_dir.joinpath(self.ai_prompt.template_file)

        yield

        # Teardown - delete tmp file
        if self.ai_prompt.template_path.exists():
            self.ai_prompt.template_path.unlink()

    def test_load_template_correct(self):
        
        # Given a valid template file...
        with open(self.ai_prompt.template_path, 'w') as f:
            yaml.dump(self.valid_template, f)
        
        # When loading the template...
        self.ai_prompt._load_template()

        # Then the template should be loaded correctly
        assert self.ai_prompt.template == self.valid_template
        
    def test_load_template_missing_prompt(self):
        
        # Given a template missing a 'prompt' key...
        with open(self.ai_prompt.template_path, 'w') as f:
            yaml.dump(self.invalid_template_missing_prompt, f)

        # When loading the template...
        with pytest.raises(KeyError, match="Template does not contain a 'prompt' key"):
            # Then an error should be raised
            self.ai_prompt._load_template()


    def test_load_template_file_not_found(self):
        
        # Given a template file that does not exist...
        self.ai_prompt.template_file = Path("test_template_not_found.yaml")
        self.ai_prompt.template_path = self.ai_prompt.template_dir.joinpath(self.ai_prompt.template_file)

        # When loading the template...
        with pytest.raises(FileNotFoundError, match="Template file not found: test_template_not_found.yaml"):
            # Then an error should be raised
            self.ai_prompt._load_template()

    def test_load_template_file_not_yaml(self):
        
        # Given a template file that is not a YAML file...
        self.ai_prompt.template_path = self.ai_prompt.template_dir.joinpath("test_template_not_yaml.txt")
        self.ai_prompt.template_path.touch()

        # When loading the template...
        with pytest.raises(OSError, match="Unable to load template file"):
            # Then an error should be raised
            self.ai_prompt._load_template()

class TestExtractAllFields:
    
    valid_template = {'prompt': 'This is a test prompt with {field1} and {field2}'}
    invalid_template_no_fields = {'prompt': 'This is a test prompt with no fields'}

    @pytest.fixture(autouse=True)
    def setup(self):
        
        # Setup - create temp file
        self.ai_prompt = object.__new__(AIPromptBase)

        yield

    def test_load_template_with_fields(self):
        
        # Given a template with fields...
        self.ai_prompt.template = self.valid_template

        # When extracting all fields...
        self.ai_prompt._extract_all_fields()

        # Then the fields should be extracted correctly
        assert self.ai_prompt.all_fields == {'field1', 'field2'}

    def test_load_template_no_fields(self):
        
        # Given a template with no fields...
        self.ai_prompt.template = self.invalid_template_no_fields

        # When extracting all fields...
        with pytest.raises(KeyError, match="No fields found in prompt template"):
            # Then an error should be raised
            self.ai_prompt._extract_all_fields()


class TestCheckMissingInputFields:
    
    valid_template = {'prompt': 'This is a test prompt with {field1} and {field2}'}
    valid_input_fields = {'field1', 'field2'}
    valid_data = {'field1': 'field1_replacement', 'field2': 'field2_replacement'}
    invalid_data = {'field1': 'field1_replacement'}

    @pytest.fixture(autouse=True)
    def setup(self):
        
        # Setup - create tmp object
        self.ai_prompt = object.__new__(AIPromptBase)
        
    
    def test_missing_input_fields(self):
        
        # Given a set of valid input fields...
        self.ai_prompt.input_fields = self.valid_input_fields

        # When checking for missing input fields with an incomplete list...
        with pytest.raises(KeyError, match="Missing required fields in data: {'field2'}"):
            # Then an error should be raised
            self.ai_prompt._check_missing_input_fields(self.invalid_data)

    def test_no_missing_input_fields(self):
        
        # Given a set of valid input fields...
        self.ai_prompt.input_fields = self.valid_input_fields

        # When checking for missing input fields with a complete list...
        self.ai_prompt._check_missing_input_fields(self.valid_data)

        # Then no error should be raised
        assert True

    
    