from policyengine_api.services.ai_analysis_service import AIAnalysisService
from policyengine_api.ai_prompts.simulation_analysis import (
    SimulationAnalysisAIPrompt,
)


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
        selected_version: str,
        time_period: str,
        impact: dict,
        policy_label: str,
        policy: dict,
        region: str,
        relevant_parameters: list[dict],
        relevant_parameter_baseline_values: list[dict],
        audience: str | None,
    ):

        # Check if the region is enhanced_cps
        is_enhanced_cps = "enhanced_us" in region

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
            is_enhanced_cps,
            selected_version,
            country_id,
            policy_label,
        )

        # Add audience description to end
        prompt += self.audience_descriptions[audience]

        print("Checking if AI analysis already exists for this prompt")
        # If a calculated record exists for this prompt, return it as a
        # streaming response
        existing_analysis = self.get_existing_analysis(prompt)
        if existing_analysis is not None:
            return existing_analysis

        print(
            "Found no existing AI analysis; triggering new analysis with Claude"
        )
        # Otherwise, pass prompt to Claude, then return streaming function
        try:
            analysis = self.trigger_ai_analysis(prompt)
            return analysis
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
        is_enhanced_cps,
        selected_version,
        country_id,
        policy_label,
    ):

        prompt_data: dict = {
            "time_period": time_period,
            "region": region,
            "currency": currency,
            "policy": policy,
            "impact": impact,
            "relevant_parameters": relevant_parameters,
            "relevant_parameter_baseline_values": relevant_parameter_baseline_values,
            "is_enhanced_cps": is_enhanced_cps,
            "selected_version": selected_version,
            "country_id": country_id,
            "policy_label": policy_label,
        }

        try:
            prompt = SimulationAnalysisAIPrompt(data=prompt_data).get_prompt()
            return prompt

        except Exception as e:
            print(e)
            raise e

    audience_descriptions = {
        "ELI5": "Write this for a layperson who doesn't know much about economics or policy. Explain fundamental concepts like taxes, poverty rates, and inequality as needed.",
        "Normal": "Write this for a policy analyst who knows a bit about economics and policy.",
        "Wonk": "Write this for a policy analyst who knows a lot about economics and policy. Use acronyms and jargon if it makes the content more concise and informative.",
    }
