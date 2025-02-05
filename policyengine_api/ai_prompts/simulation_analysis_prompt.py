from policyengine_api.ai_templates.simulation_analysis_template import (
    simulation_analysis_template,
    audience_descriptions,
)
from pydantic import BaseModel
from typing import Any, Annotated
import json


class Parameters(BaseModel):
    currency: str
    selected_version: str
    time_period: str
    impact: dict[str, dict[str, Any]]
    policy_label: str
    policy: dict[str, Any]
    region: str
    relevant_parameter_baseline_values: list[dict[str, Any]]
    relevant_parameters: list[dict[str, Any]]
    audience: str


def generate_simulation_analysis_prompt(params: Parameters) -> str:
    """
    Generate AI prompt for economy-wide simulations
    """

    Parameters.model_validate(params)

    enhanced_cps_template: str = (
        """Explicitly mention that this analysis uses PolicyEngine Enhanced CPS, constructed 
    from the 2022 Current Population Survey and the 2015 IRS Public Use File, and calibrated 
    to tax, benefit, income, and demographic aggregates."""
        if "enahnaced_us" in params["region"]
        else ""
    )

    dialect: str = "British" if params["region"] == "uk" else "American"

    data_source: str = (
        "PolicyEngine-enhanced 2019 Family Resources Survey"
        if params["region"] == "uk"
        else "2022 Current Population Survey March Supplement"
    )

    poverty_measure: str = (
        "absolute poverty before housing costs"
        if params["region"] == "uk"
        else "the Supplemental Poverty Measure"
    )

    poverty_rate_change_text: str = (
        "- After the racial breakdown of poverty rate changes, include the text: '{{povertyImpact.regular.byRace}}'"
        if params["region"] == "us"
        else ""
    )

    poverty_by_race: str = (
        json.dumps(params["impact"]["poverty_by_race"]["poverty"])
        if params["country_id"] == "us"
        else ""
    )
    poverty_by_race_text: str = (
        "- This JSON describes the baseline and reform poverty impacts by racial group (briefly "
        "describe the relative changes): " + str(poverty_by_race)
        if params["country_id"] == "us"
        else ""
    )

    audience_description: str = audience_descriptions[params["audience"]]

    country_id_uppercase: Annotated[str, "Uppercase two-letter country ID"] = (
        params["country_id"].upper()
    )
    impact_budget: dict[str, Any] = json.dumps(params["impact"]["budget"])
    impact_intra_decile: dict[str, Any] = json.dumps(
        params["impact"]["intra_decile"]
    )
    impact_decile: dict[str, Any] = json.dumps(params["impact"]["decile"])
    impact_inequality: dict[str, Any] = json.dumps(
        params["impact"]["inequality"]
    )
    impact_poverty: dict[str, Any] = json.dumps(
        params["impact"]["poverty"]["poverty"]
    )
    impact_deep_poverty: dict[str, Any] = json.dumps(
        params["impact"]["poverty"]["deep_poverty"]
    )
    impact_poverty_by_gender: dict[str, Any] = json.dumps(
        params["impact"]["poverty_by_gender"]
    )

    derived_params = {
        "enhanced_cps_template": enhanced_cps_template,
        "dialect": dialect,
        "data_source": data_source,
        "poverty_measure": poverty_measure,
        "poverty_rate_change_text": poverty_rate_change_text,
        "poverty_by_race_text": poverty_by_race_text,
        "audience_description": audience_description,
        "country_id_uppercase": country_id_uppercase,
        "impact_budget": impact_budget,
        "impact_intra_decile": impact_intra_decile,
        "impact_decile": impact_decile,
        "impact_inequality": impact_inequality,
        "impact_poverty": impact_poverty,
        "impact_deep_poverty": impact_deep_poverty,
        "impact_poverty_by_gender": impact_poverty_by_gender,
    }

    return simulation_analysis_template.format_map(
        {**params, **derived_params}
    )
