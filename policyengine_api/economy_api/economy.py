from policyengine_api.country import COUNTRIES
from policyengine_api.data import database
from policyengine_api.endpoints.policy import create_policy_reform
import json

def compute_economy(country_id: str, policy_id: str, region: str, time_period: str, options: dict):
    country = COUNTRIES.get(country_id)
    policy_json = database.get_in_table("policy", country_id=country_id, id=policy_id)["policy_json"]
    policy_data = json.loads(policy_json)
    reform = create_policy_reform(country_id, policy_data)

    simulation = country.country_package.Microsimulation(
        reform=reform,
    )

    return {
        "total_net_income": simulation.calculate(
            "household_net_income"
        ).sum(),
        "total_tax": simulation.calculate("household_tax").sum(),
        "total_benefits": simulation.calculate("household_benefits").sum(),
        "household_net_income": simulation.calculate(
            "household_net_income"
        )
        .astype(float)
        .tolist(),
        "equiv_household_net_income": simulation.calculate(
            "equiv_household_net_income",
        ).astype(float)
        .tolist(),
        "household_income_decile": simulation.calculate("household_income_decile")
        .astype(int)
        .tolist(),
        "in_poverty": simulation.calculate("in_poverty")
        .astype(bool)
        .tolist(),
        "poverty_gap": simulation.calculate("poverty_gap")
        .astype(float)
        .tolist(),
        "household_weight": simulation.calculate("household_weight")
        .astype(float)
        .tolist(),
        "household_count_people": simulation.calculate(
            "household_count_people"
        )
        .astype(int)
        .tolist(),
    }

    