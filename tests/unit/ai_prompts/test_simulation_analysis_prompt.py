import pytest
from policyengine_api.ai_prompts.simulation_analysis_prompt import (
    generate_simulation_analysis_prompt,
)
from tests.fixtures.simulation_analysis_prompt_fixtures import (
    valid_input_us,
    valid_input_uk,
    invalid_data_missing_input_field,
    given_valid_data_and_region_is_enhanced_us,
    given_valid_data_and_dataset_is_enhanced_cps,
)


class TestGenerateSimulationAnalysisPrompt:

    def test_given_valid_us_input(self, snapshot):

        snapshot.snapshot_dir = "tests/snapshots"

        prompt = generate_simulation_analysis_prompt(valid_input_us)
        snapshot.assert_match(prompt, "simulation_analysis_prompt_us.txt")

    def test_given_valid_uk_input(self, snapshot):

        snapshot.snapshot_dir = "tests/snapshots"

        prompt = generate_simulation_analysis_prompt(valid_input_uk)
        snapshot.assert_match(prompt, "simulation_analysis_prompt_uk.txt")

    def test_given_region_is_enhanced_us(self, snapshot):

        snapshot.snapshot_dir = "tests/snapshots"
        valid_enhanced_us_input_data = (
            given_valid_data_and_region_is_enhanced_us(valid_input_us)
        )

        prompt = generate_simulation_analysis_prompt(
            valid_enhanced_us_input_data
        )
        snapshot.assert_match(
            prompt, "simulation_analysis_prompt_region_enhanced_us.txt"
        )

    def test_given_dataset_is_enhanced_cps(self, snapshot):

        snapshot.snapshot_dir = "tests/snapshots"
        valid_enhanced_cps_input_data = (
            given_valid_data_and_dataset_is_enhanced_cps(valid_input_us)
        )

        prompt = generate_simulation_analysis_prompt(
            valid_enhanced_cps_input_data
        )
        snapshot.assert_match(
            prompt, "simulation_analysis_prompt_dataset_enhanced_cps.txt"
        )

    def test_given_missing_input_field(self):

        with pytest.raises(
            Exception,
            match="1 validation error for InboundParameters\ntime_period\n  Field required",
        ):
            generate_simulation_analysis_prompt(
                invalid_data_missing_input_field
            )
