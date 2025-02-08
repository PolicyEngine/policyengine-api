import pytest
from policyengine_api.ai_prompts.simulation_analysis_prompt import (
    generate_simulation_analysis_prompt,
)
from tests.fixtures.simulation_analysis_prompt_fixtures import (
    valid_input_data,
    invalid_data_missing_input_field,
)


class TestGenerateSimulationAnalysisPrompt:

    def test_given_all_required_keys_present(self):

        prompt = generate_simulation_analysis_prompt(valid_input_data)

        # Is there a way to validate this works properly without
        # having to check the entire prompt?

    def test_given_missing_input_field(self):

        with pytest.raises(
            Exception,
            match="1 validation error for InboundParameters\ntime_period\n  Field required",
        ):
            generate_simulation_analysis_prompt(
                invalid_data_missing_input_field
            )
