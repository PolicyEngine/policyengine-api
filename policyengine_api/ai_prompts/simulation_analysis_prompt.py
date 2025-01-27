from policyengine_api.utils import AIPromptBase
import json


class SimulationAnalysisAIPrompt(AIPromptBase):
    """
    Generate AI prompt for economy-wide simulations
    """

    name = "simulation_analysis"

    def __init__(self, data: dict):
        super().__init__(self.name)

        # These fields are generated within _transform_data() and
        # do not need to be included in the "data" arg
        self.generated_fields: set = set(
            (
                "enhanced_cps_template",
                "dialect",
                "data_source",
                "poverty_measure",
                "poverty_rate_change_text",
                "poverty_by_race_text",
                "audience_description",
                "chart_slug_distribution",
                "chart_slug_poverty_age",
                "chart_slug_inequality",
                "impact_budget",
                "impact_intra_decile",
                "impact_decile",
                "impact_inequality",
                "impact_poverty",
                "impact_deep_poverty",
                "impact_poverty_by_gender",
                "country_id_uppercase",
            )
        )

        # This field cannot be parsed from the template itself;
        # it is used within _transform_data() and must be included in
        # the "data" arg
        self.non_parsed_input_fields: set = set(("audience", "country_id"))

        self._update_dependent_fields()
        self.data: dict = self._transform_data(data)

    def _transform_data(self, data: dict) -> dict:
        """
        Add additional fields to the data before formatting the prompt template.
        """
        print("Transforming data for simulation analysis AI prompt")

        self._check_missing_input_fields(data)

        is_enhanced_cps = "enahnaced_us" in data["region"]

        enhanced_cps_template = (
            """Explicitly mention that this analysis uses PolicyEngine Enhanced CPS, constructed 
        from the 2022 Current Population Survey and the 2015 IRS Public Use File, and calibrated 
        to tax, benefit, income, and demographic aggregates."""
            if is_enhanced_cps
            else ""
        )

        dialect = "British" if data["country_id"] == "uk" else "American"

        data_source = (
            "PolicyEngine-enhanced 2019 Family Resources Survey"
            if data["country_id"] == "uk"
            else "2022 Current Population Survey March Supplement"
        )

        poverty_measure = (
            "absolute poverty before housing costs"
            if data["country_id"] == "uk"
            else "the Supplemental Poverty Measure"
        )

        poverty_rate_change_text = (
            "- After the racial breakdown of poverty rate changes, include the text: '{{povertyImpact.regular.byRace}}'"
            if data["country_id"] == "us"
            else ""
        )

        poverty_by_race = (
            json.dumps(data["impact"]["poverty_by_race"]["poverty"])
            if data["country_id"] == "us"
            else ""
        )
        poverty_by_race_text = (
            "- This JSON describes the baseline and reform poverty impacts by racial group (briefly "
            "describe the relative changes): " + str(poverty_by_race)
            if data["country_id"] == "us"
            else ""
        )

        audience_description = self.audience_descriptions[data["audience"]]

        return {
            **data,
            "audience_description": audience_description,
            "enhanced_cps_template": enhanced_cps_template,
            "dialect": dialect,
            "data_source": data_source,
            "poverty_measure": poverty_measure,
            "poverty_rate_change_text": poverty_rate_change_text,
            "poverty_by_race_text": poverty_by_race_text,
            "country_id_uppercase": data["country_id"].upper(),
            "chart_slug_distribution": "{{distributionalImpact.incomeDecile.relative}}",
            "chart_slug_poverty_age": "{{povertyImpact.regular.byAge}}",
            "chart_slug_inequality": "{{inequalityImpact}}",
            "impact_budget": json.dumps(data["impact"]["budget"]),
            "impact_intra_decile": json.dumps(data["impact"]["intra_decile"]),
            "impact_decile": json.dumps(data["impact"]["decile"]),
            "impact_inequality": json.dumps(data["impact"]["inequality"]),
            "impact_poverty": json.dumps(data["impact"]["poverty"]["poverty"]),
            "impact_deep_poverty": json.dumps(
                data["impact"]["poverty"]["deep_poverty"]
            ),
            "impact_poverty_by_gender": json.dumps(
                data["impact"]["poverty_by_gender"]
            ),
        }

    audience_descriptions = {
        "ELI5": "Write this for a layperson who doesn't know much about economics or policy. Explain fundamental concepts like taxes, poverty rates, and inequality as needed.",
        "Normal": "Write this for a policy analyst who knows a bit about economics and policy.",
        "Wonk": "Write this for a policy analyst who knows a lot about economics and policy. Use acronyms and jargon if it makes the content more concise and informative.",
    }
