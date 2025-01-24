import json

from policyengine_api.services.ai_analysis_service import AIAnalysisService
from policyengine_api.utils.ai_prompt_manager import AIPromptManager

prompt_manager = AIPromptManager()    

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
        
        enhanced_cps_template = """Explicitly mention that this analysis uses PolicyEngine Enhanced CPS, constructed 
          from the 2022 Current Population Survey and the 2015 IRS Public Use File, and calibrated 
          to tax, benefit, income, and demographic aggregates.""" if is_enhanced_cps else ''
        
        dialect = 'British' if country_id == 'uk' else 'American'

        data_source = 'PolicyEngine-enhanced 2019 Family Resources Survey' if country_id == 'uk' else '2022 Current Population Survey March Supplement'

        poverty_measure = "absolute poverty before housing costs" if country_id == 'uk' else 'the Supplemental Poverty Measure'

        poverty_rate_change_text = "- After the racial breakdown of poverty rate changes, include the text: '{{povertyImpact.regular.byRace}}'" if country_id == 'us' else ''

        poverty_by_race = json.dumps(impact["poverty_by_race"]["poverty"]) if country_id == 'us' else ''
        poverty_by_race_text = (
          "- This JSON describes the baseline and reform poverty impacts by racial group (briefly "
          "describe the relative changes): " + str(poverty_by_race) if country_id == "us" else ""
        )

        try:
            data_to_replace = {
                "country_id": country_id,
                "country_id_uppercase": country_id.upper(),
                "currency": currency,
                "data_source": data_source,
                "dialect": dialect,
                "enhanced_cps_template": enhanced_cps_template,
                "impact": impact,
                "is_enhanced_cps": is_enhanced_cps,
                "policy": policy,
                "policy_label": policy_label,
                "poverty_by_race_text": poverty_by_race_text,
                "poverty_measure": poverty_measure,
                "poverty_rate_change_text": poverty_rate_change_text,
                "region": region,
                "relevant_parameter_baseline_values": json.dumps(relevant_parameter_baseline_values),
                "relevant_parameters": json.dumps(relevant_parameters),
                "selected_version": selected_version,
                "time_period": time_period,
                "chart_slug_distribution": "{{distributionalImpact.incomeDecile.relative}}",
                "chart_slug_poverty_age": "{{povertyImpact.regular.byAge}}",
                "chart_slug_inequality": "{{inequalityImpact}}",
                "impact_budget": json.dumps(impact["budget"]),
                "impact_intra_decile": json.dumps(impact["intra_decile"]),
                "impact_decile": json.dumps(impact["decile"]),
                "impact_inequality": json.dumps(impact["inequality"]),
                "impact_poverty": json.dumps(impact["poverty"]["poverty"]),
                "impact_deep_poverty": json.dumps(impact["poverty"]["deep_poverty"]),
                "impact_poverty_by_gender": json.dumps(impact["poverty_by_gender"]),
            }

            prompt: str = prompt_manager.get_prompt(
                "simulation_analysis",
                **data_to_replace
            )

            return prompt
        except Exception as e:
            print(e)
            raise e

    audience_descriptions = {
        "ELI5": "Write this for a layperson who doesn't know much about economics or policy. Explain fundamental concepts like taxes, poverty rates, and inequality as needed.",
        "Normal": "Write this for a policy analyst who knows a bit about economics and policy.",
        "Wonk": "Write this for a policy analyst who knows a lot about economics and policy. Use acronyms and jargon if it makes the content more concise and informative.",
    }
