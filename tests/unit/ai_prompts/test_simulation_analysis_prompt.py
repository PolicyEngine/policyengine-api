import pytest
from policyengine_api.ai_prompts.simulation_analysis_prompt import (
    SimulationAnalysisAIPrompt,
)
from tests.fixtures.simulation_analysis_prompt_fixtures import (
    valid_input_data,
    valid_output_data,
)

invalid_data_missing_input_field = {
    k: v for k, v in valid_input_data.items() if k != "time_period"
}
invalid_data_missing_non_parsed_input_field = {
    k: v for k, v in valid_input_data.items() if k != "audience"
}


class TestInit:

    def test_has_all_required_fields(self):

        # Given valid data...

        # When we initialize the SimulationAnalysisAIPrompt...
        prompt = SimulationAnalysisAIPrompt(valid_input_data)

        # Then the prompt should have the correct data
        assert prompt.data == valid_output_data

    def test_missing_input_fields(self):
        # Given invalid data with a missing input field...

        # When we initialize the SimulationAnalysisAIPrompt...
        with pytest.raises(
            KeyError, match="Missing required fields in data: {'time_period'}"
        ):
            # Then we should raise a KeyError
            prompt = SimulationAnalysisAIPrompt(
                invalid_data_missing_input_field
            )

    def test_missing_non_parsed_input_fields(self):

        # Given invalid data with a missing non-parsed input field...

        # When we initialize the SimulationAnalysisAIPrompt...
        with pytest.raises(
            KeyError, match="Missing required fields in data: {'audience'}"
        ):
            # Then we should raise a KeyError
            prompt = SimulationAnalysisAIPrompt(
                invalid_data_missing_non_parsed_input_field
            )
