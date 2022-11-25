from policyengine_api.country import COUNTRIES
from policyengine_api.data import database
from policyengine_api.endpoints.policy import create_policy_reform
from policyengine_core.simulations import Microsimulation
import json

def compute_general_economy(
    simulation: Microsimulation
) -> dict:
    return {
        "total_net_income": simulation.calculate("household_net_income").sum(),
        "total_tax": simulation.calculate("household_tax").sum(),
        "total_benefits": simulation.calculate("household_benefits").sum(),
        "household_net_income": simulation.calculate("household_net_income")
        .astype(float)
        .tolist(),
        "equiv_household_net_income": simulation.calculate(
            "equiv_household_net_income",
        )
        .astype(float)
        .tolist(),
        "household_income_decile": simulation.calculate(
            "household_income_decile"
        )
        .astype(int)
        .tolist(),
        "in_poverty": simulation.calculate("in_poverty").astype(bool).tolist(),
        "person_in_poverty": simulation.calculate(
            "in_poverty", map_to="person"
        )
        .astype(bool)
        .tolist(),
        "person_weight": simulation.calculate("person_weight")
        .astype(float)
        .tolist(),
        "age": simulation.calculate("age").astype(int).tolist(),
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
        "type": "general",
    }

def compute_cliff_impact(
    simulation: Microsimulation,
):
    cliff_gap = simulation.calculate("cliff_gap")
    is_on_cliff = simulation.calculate("is_on_cliff")
    total_cliff_gap = cliff_gap.sum()
    total_adults = simulation.calculate("is_adult").sum()
    cliff_share = is_on_cliff.sum() / total_adults
    return {
        "cliff_gap": float(total_cliff_gap),
        "cliff_share": float(cliff_share),
        "type": "cliff",
    }


def compute_economy(
    country_id: str,
    policy_id: str,
    region: str,
    time_period: str,
    options: dict,
):
    country = COUNTRIES.get(country_id)
    policy_json = database.get_in_table(
        "policy", country_id=country_id, id=policy_id
    )["policy_json"]
    policy_data = json.loads(policy_json)
    reform = create_policy_reform(country_id, policy_data)

    simulation = country.country_package.Microsimulation(
        reform=reform,
    )

    original_household_weight = simulation.calculate("household_weight").values

    if country_id == "uk":
        if region != "uk":
            region_values = simulation.calculate("region").values
            region_decoded = dict(
                eng="ENGLAND",
                wales="WALES",
                scot="SCOTLAND",
                ni="NORTHERN_IRELAND",
            )
            simulation.set_input("household_weight", 2022, original_household_weight * (region_values == region_decoded))
    elif country_id == "us":
        if region != "us":
            region_values = simulation.calculate("state_code_str").values
            simulation.set_input("household_weight", 2022, original_household_weight * (region_values == region.upper()))

    if options.get("target") == "cliff":
        return compute_cliff_impact(simulation)

    return compute_general_economy(simulation)
