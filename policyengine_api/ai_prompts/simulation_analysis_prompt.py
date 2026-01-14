from policyengine_api.ai_templates.simulation_analysis_template import (
    simulation_analysis_template,
    audience_descriptions,
)
from pydantic import BaseModel
from typing import Any, Annotated
import json


class InboundParameters(BaseModel):
    currency: Annotated[str, "The currency symbol to be used (e.g., $, £)"]
    country_id: str
    dataset: str | None
    selected_version: str
    time_period: str
    impact: dict[str, dict[str, Any] | str | None]
    policy_label: str
    policy: dict[str, Any]
    region: str
    relevant_parameter_baseline_values: list[dict[str, Any]]
    relevant_parameters: list[dict[str, Any]]
    audience: str


class AllParameters(InboundParameters):
    model_config = {"exclude": {"audience"}}
    enhanced_cps_template: str
    dialect: str
    data_source: str
    poverty_measure: str
    poverty_rate_change_text: str
    poverty_by_race_text: str
    audience_description: str
    country_id_uppercase: Annotated[str, "Uppercase two-letter country ID"]
    impact_budget: Annotated[str, "JSON deserialized to string"]
    impact_intra_decile: Annotated[str, "JSON deserialized to string"]
    impact_decile: Annotated[str, "JSON deserialized to string"]
    impact_inequality: Annotated[str, "JSON deserialized to string"]
    impact_poverty: Annotated[str, "JSON deserialized to string"]
    impact_deep_poverty: Annotated[str, "JSON deserialized to string"]
    impact_poverty_by_gender: Annotated[str, "JSON deserialized to string"]


def generate_simulation_analysis_prompt(params: InboundParameters) -> str:
    """
    Generate AI prompt for economy-wide simulations
    """

    parameters: InboundParameters = InboundParameters.model_validate(params)

    enhanced_cps_template: str = (
        """- Explicitly mention that this analysis uses PolicyEngine Enhanced CPS, constructed 
    from the 2023 Current Population Survey and the 2015 IRS Public Use File, and calibrated 
    to tax, benefit, income, and demographic aggregates."""
        if parameters.dataset == "enhanced_cps"
        else ""
    )

    dialect: str = "British" if parameters.region == "uk" else "American"

    data_source: str = (
        "PolicyEngine-enhanced 2019 Family Resources Survey"
        if parameters.region == "uk"
        else "2022 Current Population Survey March Supplement"
    )

    poverty_measure: str = (
        "absolute poverty before housing costs"
        if parameters.region == "uk"
        else "the Supplemental Poverty Measure"
    )

    poverty_rate_change_text: str = (
        "- After the racial breakdown of poverty rate changes, include the text: '{{povertyImpact.regular.byRace}}'"
        if parameters.region == "us"
        else ""
    )

    poverty_by_race: str = (
        json.dumps(parameters.impact["poverty_by_race"]["poverty"])
        if parameters.country_id == "us"
        else ""
    )
    poverty_by_race_text: str = (
        "- This JSON describes the baseline and reform poverty impacts by racial group (briefly "
        "describe the relative changes): " + str(poverty_by_race)
        if parameters.country_id == "us"
        else ""
    )

    audience_description: str = audience_descriptions[parameters.audience]

    country_id_uppercase: Annotated[str, "Uppercase two-letter country ID"] = (
        parameters.country_id.upper()
    )

    impact_budget: str = json.dumps(parameters.impact["budget"])
    impact_intra_decile: dict[str, Any] = json.dumps(parameters.impact["intra_decile"])
    impact_decile: str = json.dumps(parameters.impact["decile"])
    impact_inequality: str = json.dumps(parameters.impact["inequality"])
    impact_poverty: str = json.dumps(parameters.impact["poverty"]["poverty"])
    impact_deep_poverty: str = json.dumps(parameters.impact["poverty"]["deep_poverty"])
    impact_poverty_by_gender: str = json.dumps(parameters.impact["poverty_by_gender"])

    all_parameters: AllParameters = AllParameters.model_validate(
        {
            **parameters.dict(),
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
    )

    return simulation_analysis_template.format_map(all_parameters.dict())
