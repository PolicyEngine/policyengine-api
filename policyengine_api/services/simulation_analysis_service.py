from policyengine_api.services.ai_analysis_service import AIAnalysisService
from policyengine_api.services.ai_prompt_service import AIPromptService
from typing import Generator, Literal

ai_prompt_service = AIPromptService()


class SimulationAnalysisService(AIAnalysisService):
    """
    Service for generating AI analysis of economy-wide simulation
    runs; this is connected with the simulation_analysis route and
    analysis database table
    """

    def __init__(self):
        super().__init__()

    def execute_analysis(
        self,
        country_id: str,
        currency: str,
        dataset: str | None,
        selected_version: str,
        time_period: str,
        impact: dict,
        policy_label: str,
        policy: dict,
        region: str,
        relevant_parameters: list[dict],
        relevant_parameter_baseline_values: list[dict],
        audience: str | None,
    ) -> tuple[Generator[str, None, None] | str, Literal["streaming", "static"]]:
        """
        Execute AI analysis for economy-wide simulation

        Returns a tuple of:
        - The AI analysis as either a streaming output (if new) or
          a string (if existing in database)
        - The return type (either "streaming" or "static")

        """

        print("Generating prompt for economy-wide simulation analysis")

        # Create prompt based on data
        prompt = self._generate_simulation_analysis_prompt(
            time_period,
            region,
            currency,
            policy,
            impact,
            relevant_parameters,
            relevant_parameter_baseline_values,
            selected_version,
            country_id,
            policy_label,
            audience,
            dataset=dataset,
        )

        print("Checking if AI analysis already exists for this prompt")
        # If a calculated record exists for this prompt, return it as a
        # streaming response
        existing_analysis = self.get_existing_analysis(prompt)
        if existing_analysis is not None:
            return existing_analysis, "static"

        print("Found no existing AI analysis; triggering new analysis with Claude")
        # Otherwise, pass prompt to Claude, then return streaming function
        try:
            analysis = self.trigger_ai_analysis(prompt)
            return analysis, "streaming"
        except Exception as e:
            raise e

    def _generate_simulation_analysis_prompt(
        self,
        time_period,
        region,
        currency,
        policy,
        impact,
        relevant_parameters,
        relevant_parameter_baseline_values,
        selected_version,
        country_id,
        policy_label,
        audience,
        dataset,
    ):

        prompt_data: dict = {
            "time_period": time_period,
            "region": region,
            "currency": currency,
            "policy": policy,
            "impact": impact,
            "relevant_parameters": relevant_parameters,
            "relevant_parameter_baseline_values": relevant_parameter_baseline_values,
            "selected_version": selected_version,
            "country_id": country_id,
            "policy_label": policy_label,
            "audience": audience,
            "dataset": dataset,
        }

        try:
            prompt = ai_prompt_service.get_prompt("simulation_analysis", prompt_data)
            return prompt

        except Exception as e:
            raise e
